#!/usr/bin/env python3
"""Write-approval gate + pending store for memory and skill writes.

A per-subsystem boolean ``write_approval`` gates the agent's cross-session writes —
**memory** (MEMORY.md / USER.md) and **skills** (SKILL.md + files) — from either
origin (**foreground** turn or **background_review** fork). ``false`` (default)
writes freely; ``true`` never commits directly: it prompts inline (memory,
interactive CLI only) or **stages** the write under
``<HERMES_HOME>/pending/{memory,skills}/<id>.json`` for out-of-band review.
"""

from __future__ import annotations

import ctypes
import difflib
import errno
import functools
import json
import logging
import math
import os
import re
import stat
import threading
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

# Subsystem identifiers
MEMORY = "memory"
SKILLS = "skills"
_SUBSYSTEMS = (MEMORY, SKILLS)

# Per-subsystem config key. Intentionally a single boolean with no "block all writes"
# state — to disable a subsystem use its own enable flag (e.g. ``memory.memory_enabled``).
CONFIG_KEY = "write_approval"
_TRUTHY_STRINGS = frozenset({"on", "true", "yes", "1", "approve", "enabled"})


# --- Config resolution ---

def write_approval_enabled(subsystem: str) -> bool:
    """Read ``<subsystem>.write_approval``; any unset/invalid value means gate off."""
    if subsystem not in _SUBSYSTEMS:
        return False
    try:
        from hermes_cli.config import load_config, cfg_get
        return _normalize_enabled(cfg_get(load_config(), subsystem, CONFIG_KEY, default=False))
    except Exception:
        return False


def _normalize_enabled(value: Any) -> bool:
    """Coerce a config value to bool; unknown → False (gate off). The string branch
    covers hand-edited configs (YAML already parses bare on/off/yes/no)."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in _TRUTHY_STRINGS


# --- Pending store (file-backed) ---

# How stage_write mints ids (uuid4().hex[:8]). Ids are typed by people (``/skills approve <id>``),
# so only this exact shape names a record: never a path, a prefix, or another case (#119997).
_PENDING_ID_RE = re.compile(r"[0-9a-f]{8}")
# ``<id>.json`` moves here while an approval applies it; a leftover one needs a human (see claim_pending).
_CLAIM_SUFFIX = ".applying.json"
_STORE_LOCK = ".store.lock"  # Windows only: POSIX locks the pinned store directory itself
_LOCK_TIMEOUT_S = 15.0
_nt_lock_holders: dict[str, threading.local] = {}

# Store states of one id (peek_pending, claim_pending, discard_pending).
PENDING, CLAIMED, MISSING, BUSY, INVALID, CHANGED, STORE_ERROR, DISCARDED = (
    "pending", "claimed", "missing", "busy", "invalid", "changed", "store_error", "discarded")


class PendingStoreError(OSError):
    """The pending store cannot be used safely (redirected out of the Hermes home, or locked too long)."""


class _Changed(Exception):
    """The source name stopped naming the record being moved."""


def is_pending_id(value: Any) -> bool:
    return isinstance(value, str) and _PENDING_ID_RE.fullmatch(value) is not None


def _pending_dir(subsystem: str) -> Path:
    """``<HERMES_HOME>/pending/<subsystem>``. Refuses a store that a symlink or junction under the Hermes
    home redirects elsewhere: reads, claims and deletes would then act on files outside it."""
    if subsystem not in _SUBSYSTEMS:
        raise ValueError(f"unknown write-approval subsystem {subsystem!r}")
    home = get_hermes_home()
    d = home / "pending" / subsystem
    if any(p.is_symlink() for p in (d.parent, d)) or d.resolve() != home.resolve() / "pending" / subsystem:
        raise PendingStoreError(f"the {subsystem} pending store {d} is redirected by a link; refusing to use it")
    return d


def _pending_path(subsystem: str, pending_id: str) -> Path:
    if not is_pending_id(pending_id):
        raise ValueError(f"invalid pending id {pending_id!r}")
    return _pending_dir(subsystem) / f"{pending_id}.json"


def _claimed_ids(d: Path) -> set[str]:
    return {i for i in (p.name[:-len(_CLAIM_SUFFIX)] for p in d.glob(f"*{_CLAIM_SUFFIX}")) if is_pending_id(i)}


def _pending_files(subsystem: str) -> list:
    """Files named like a pending record; an id that also has a claim is not pending (it is listed for
    reconciliation instead, and ``reject all`` must not delete it under the person reconciling it)."""
    d = _pending_dir(subsystem)
    if not d.exists():
        return []
    claimed = _claimed_ids(d)
    return [p for p in d.glob("*.json") if is_pending_id(p.stem) and p.stem not in claimed]


def _valid_created_at(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:  # an int too large for a float
        return False


def _parse_record(fd: int, subsystem: str, pending_id: str
                  ) -> tuple[Optional[dict[str, Any]], Optional[tuple[int, int]]]:
    """``(record, (st_dev, st_ino))`` from an open fd (closed here). The identity is the fstat of the very
    bytes that were parsed; the record is None unless it is a regular file holding a well-formed record
    for exactly this subsystem and id."""
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):  # a FIFO or device is never a record
            return None, None
        try:
            record = json.loads(fh.read().decode("utf-8-sig"))
        except (OSError, ValueError):
            return None, (st.st_dev, st.st_ino)
    if (not isinstance(record, dict) or record.get("id") != pending_id or record.get("subsystem") != subsystem
            or not isinstance(record.get("payload"), dict) or not _valid_created_at(record.get("created_at"))):
        return None, (st.st_dev, st.st_ino)
    return record, (st.st_dev, st.st_ino)


_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _read_record(path: Path, subsystem: str, pending_id: str) -> Optional[dict[str, Any]]:
    """The record at ``path`` (a symlink is refused, not followed), or None."""
    if path.is_symlink():
        return None
    try:
        fd = os.open(path, _READ_FLAGS)
    except OSError:
        return None
    return _parse_record(fd, subsystem, pending_id)[0]


def stage_write(subsystem: str, payload: dict[str, Any], *, summary: str, origin: str) -> dict[str, Any]:
    """Persist a pending write and return its record (``id`` + metadata). ``payload`` is the exact
    kwargs to replay the write on approval; ``origin`` is ``foreground`` or ``background_review``.
    Published under the store lock and never over an existing name, so a staged write can never
    replace a record (or a claim) an approval is checking, moving or restoring.
    Best-effort: on disk failure it logs and still returns a record — the write is lost, which is
    the safe failure for an approval gate (nothing silently committed)."""
    record = {
        "id": uuid.uuid4().hex[:8], "subsystem": subsystem, "action": payload.get("action", ""),
        "summary": (summary or "").strip(), "origin": origin or "foreground",
        "created_at": time.time(), "payload": payload,
    }
    try:
        with _store_lock(subsystem, create=True) as st:
            for _ in range(8):
                if not (st.lexists(f"{record['id']}.json") or st.lexists(f"{record['id']}{_CLAIM_SUFFIX}")):
                    try:
                        st.publish(f"{record['id']}.json", _record_bytes(record))
                        break
                    except FileExistsError:
                        pass
                record["id"] = uuid.uuid4().hex[:8]
            else:
                raise FileExistsError(f"no free pending id in {st.path}")
    except Exception as e:  # pragma: no cover - disk failure path
        logger.error("Failed to stage pending %s write: %s", subsystem, e, exc_info=True)
    return record


def _record_bytes(record: dict[str, Any]) -> bytes:
    try:
        return json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:  # surrogate-escaped text (non-UTF-8 paths) is kept as escapes
        return json.dumps(record, indent=2, ensure_ascii=True).encode("utf-8")


def list_pending(subsystem: str) -> list[dict[str, Any]]:
    """Return all approvable pending records for ``subsystem``, oldest first (claims and invalid
    records are reported by :func:`list_unapprovable`)."""
    records: list[dict[str, Any]] = []
    for p in _pending_files(subsystem):
        record = _read_record(p, subsystem, p.stem)
        if record is None:
            logger.warning("Skipping unreadable or invalid pending record: %s", p)
            continue
        records.append(record)
    records.sort(key=lambda r: r["created_at"])
    return records


def list_unapprovable(subsystem: str) -> list[tuple[str, str]]:
    """``(id, kind)`` for store entries a person must look at: ``"claimed"`` — an approval was
    interrupted or could not finish (``<id>.applying.json``), never retried automatically — and
    ``"invalid"`` — a record that is unreadable, redirected, or not what its file name says."""
    d = _pending_dir(subsystem)
    if not d.exists():
        return []
    out = [(i, "claimed") for i in _claimed_ids(d)]
    out += [(p.stem, "invalid") for p in _pending_files(subsystem) if _read_record(p, subsystem, p.stem) is None]
    return sorted(out)


def peek_pending(subsystem: str, pending_id: str) -> tuple[str, Optional[dict[str, Any]]]:
    """``(PENDING, record)`` for an approvable record, else ``(MISSING|BUSY|INVALID, None)``. Changes
    nothing; an approval passes the record on to :func:`claim_pending` as what was reviewed."""
    path = _pending_path(subsystem, pending_id)
    if os.path.lexists(path.with_name(f"{pending_id}{_CLAIM_SUFFIX}")):
        return BUSY, None
    if not os.path.lexists(path):
        return MISSING, None
    record = _read_record(path, subsystem, pending_id)
    return (PENDING, record) if record is not None else (INVALID, None)


def is_claimed(subsystem: str, pending_id: str) -> bool:
    return is_pending_id(pending_id) and peek_pending(subsystem, pending_id)[0] == BUSY


def get_pending(subsystem: str, pending_id: str) -> Optional[dict[str, Any]]:
    """Return a single valid pending record by id, or None (also while it is claimed)."""
    return peek_pending(subsystem, pending_id)[1] if is_pending_id(pending_id) else None


def pending_count(subsystem: str) -> int:
    """Cheap count of approvable-looking pending records (for notification badges): files named by a
    minted id that no claim holds. Not parsed, so an invalid record still counts until rejected."""
    with suppress(Exception):
        return len(_pending_files(subsystem))
    return 0


def has_review_items(subsystem: str) -> bool:
    """Whether ``/<subsystem>`` review has anything to show: pending records, claims to reconcile, or
    invalid records. True for a store it refuses, so the refusal is shown rather than hidden."""
    try:
        return pending_count(subsystem) > 0 or bool(list_unapprovable(subsystem))
    except PendingStoreError:
        return True


# --- Store mutations: claim, release, restore, discard ---
# One pending record is one transaction. Approving it first moves ``<id>.json`` to
# ``<id>.applying.json`` in the same directory, under the store lock and without ever replacing a file,
# so of two approvers (two chat surfaces, a double-sent command) exactly one applies it, and an approve
# and a reject of one id never both succeed. The claim is bound to the record that was reviewed and to
# the bytes that were checked: a record changed or replaced in between goes back for fresh review. Only
# a confirmed no-effect failure puts the record back; a crash, an uncertain outcome or a failed cleanup
# leaves the claim for a person to reconcile. Not exactly-once side effects: a claim is never replayed.

_RENAME_NOREPLACE = 1  # Linux renameat2
_RENAME_EXCL = 0x4  # macOS renameatx_np


@functools.cache
def _libc():
    if os.name == "nt":
        return None
    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None


def _renameat_noreplace(dir_fd: int, src: str, dst: str) -> bool:
    """Atomically rename ``src`` to ``dst`` inside ``dir_fd`` unless ``dst`` exists (FileExistsError).
    False when this kernel, libc or filesystem has no such rename (the caller falls back)."""
    libc = _libc()
    for name, flag in (("renameat2", _RENAME_NOREPLACE), ("renameatx_np", _RENAME_EXCL)):
        fn = getattr(libc, name, None) if libc is not None else None
        if fn is None:
            continue
        if fn(dir_fd, os.fsencode(src), dir_fd, os.fsencode(dst), flag) == 0:
            return True
        err = ctypes.get_errno()
        if err in (errno.ENOSYS, errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL),
                   getattr(errno, "EOPNOTSUPP", errno.EINVAL)):
            return False
        raise OSError(err, os.strerror(err), dst)  # EEXIST -> FileExistsError, ENOENT -> FileNotFoundError
    return False


class _Store:
    """One subsystem's store, pinned for the duration of a locked mutation: on POSIX every name is
    resolved relative to a directory fd opened without following links and checked to be the store,
    so swapping the directory for a link after the check cannot move files outside it."""

    def __init__(self, path: Path, fd: Optional[int]):
        self.path, self.fd = path, fd

    def _kw(self) -> dict[str, Any]:
        return {"dir_fd": self.fd} if self.fd is not None else {}

    def _p(self, name: str):
        return name if self.fd is not None else self.path / name

    def lexists(self, name: str) -> bool:
        try:
            os.stat(self._p(name), follow_symlinks=False, **self._kw())
            return True
        except FileNotFoundError:
            return False

    def identity(self, name: str) -> Optional[tuple[int, int]]:
        try:
            st = os.stat(self._p(name), follow_symlinks=False, **self._kw())
        except FileNotFoundError:
            return None
        return st.st_dev, st.st_ino

    def read(self, name: str, subsystem: str, pending_id: str):
        try:
            fd = os.open(self._p(name), _READ_FLAGS, **self._kw())
        except OSError:
            return None, self.identity(name)
        return _parse_record(fd, subsystem, pending_id)

    def unlink(self, name: str) -> None:
        os.unlink(self._p(name), **self._kw())

    def publish(self, name: str, data: bytes) -> None:
        """Write ``data`` to a private temp file, then give it ``name`` without replacing anything."""
        tmp = f".{name}.{uuid.uuid4().hex}.tmp"
        fd = os.open(self._p(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600,
                     **self._kw())
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            self.move_no_replace(tmp, name)
        except BaseException:
            with suppress(OSError):
                self.unlink(tmp)
            raise

    def move_no_replace(self, src: str, dst: str) -> None:
        """Give the file named ``src`` the name ``dst``, never replacing ``dst`` (FileExistsError) and
        never dropping a ``src`` that stopped naming the moved file (_Changed)."""
        if self.fd is None:  # Windows: a rename never replaces its target
            os.rename(self._p(src), self._p(dst))
            return
        if _renameat_noreplace(self.fd, src, dst):
            return
        kw = {"src_dir_fd": self.fd, "dst_dir_fd": self.fd}
        try:
            if os.link in os.supports_follow_symlinks:
                os.link(src, dst, follow_symlinks=False, **kw)
            else:
                os.link(src, dst, **kw)
        except (FileExistsError, FileNotFoundError):
            raise
        except OSError:  # no hard links either: every store writer holds the lock, so nothing appears at dst
            if self.lexists(dst):
                raise FileExistsError(errno.EEXIST, "already exists", dst) from None
            os.rename(src, dst, **kw)
            return
        linked = self.identity(dst)
        # Drop the old name without a check-then-unlink window: move whatever ``src`` names now to a
        # fresh private name (a rename to a new name replaces nothing), and delete it only if it is the
        # inode we linked; anything else is a newcomer, which goes back under ``src`` untouched.
        aside = f".{src}.{uuid.uuid4().hex}.aside"
        try:
            os.rename(src, aside, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        except OSError:  # never leave one record under both names
            with suppress(OSError):
                self.unlink(dst)
            raise
        if self.identity(aside) == linked:
            self.unlink(aside)
            return
        with suppress(OSError):  # src was replaced after the link: keep the newcomer, undo ours
            if self.identity(dst) == linked:
                self.unlink(dst)
        try:
            os.link(aside, src, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            self.unlink(aside)
        except OSError:
            logger.warning("write_approval: a record replaced mid-claim is kept as %s/%s", self.path, aside)
        raise _Changed(src)


@contextmanager
def _store_lock(subsystem: str, *, create: bool = False):
    """Hold the subsystem's cross-process store lock and yield the pinned :class:`_Store`, or None when
    the store does not exist and ``create`` is off (nothing to change; only staging creates the store,
    through mkdir_under_hermes_home, so a lock never conjures a deleted profile's directories).

    POSIX: the directory is opened without following links, checked to be the store, and locked
    itself (flock on that fd) — no lock file, so nothing is ever opened through a path that a link
    could redirect. Not re-entrant: no store operation runs another one while holding the lock."""
    d = _pending_dir(subsystem)
    if create:
        from hermes_constants import mkdir_under_hermes_home
        mkdir_under_hermes_home(d)
    if os.name == "nt":
        with _nt_store_lock(subsystem, d) as st:
            yield st
        return
    try:
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        yield None
        return
    except OSError as e:  # ELOOP / ENOTDIR: the store itself was replaced by a link or a file
        raise PendingStoreError(f"the {subsystem} pending store {d} is not a plain directory ({e})") from e
    try:
        _flock_with_deadline(fd, subsystem)
        pinned, now = os.fstat(fd), os.stat(_pending_dir(subsystem), follow_symlinks=False)
        if (pinned.st_dev, pinned.st_ino) != (now.st_dev, now.st_ino):  # swapped after it was opened
            raise PendingStoreError(f"the {subsystem} pending store {d} changed while it was opened")
        yield _Store(d, fd)
    finally:
        os.close(fd)  # also releases the flock


def _flock_with_deadline(fd: int, subsystem: str) -> None:
    import fcntl  # windows-footgun: ok — POSIX only (the nt branch of _store_lock takes _nt_store_lock)
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise PendingStoreError(f"Timed out waiting for the {subsystem} pending store") from None
            time.sleep(0.05)


@contextmanager
def _nt_store_lock(subsystem: str, d: Path):
    """Windows: no directory fds, so the store path is re-checked under a lock file inside it."""
    if not d.is_dir():
        yield None
        return
    from hermes_cli.auth import _file_lock
    lock_path = d / _STORE_LOCK
    holder = _nt_lock_holders.setdefault(str(lock_path), threading.local())  # one holder per lock path
    try:
        with _file_lock(lock_path, holder, _LOCK_TIMEOUT_S, f"Timed out waiting for the {subsystem} pending store"):
            yield _Store(_pending_dir(subsystem), None)
    except TimeoutError as e:
        raise PendingStoreError(str(e)) from e


def claim_pending(subsystem: str, pending_id: str, expected: Optional[dict[str, Any]] = None
                  ) -> tuple[str, Optional[dict[str, Any]]]:
    """Claim a pending record for applying: ``(CLAIMED, record)``, or a refusal with the store left as it
    was: MISSING, BUSY (claimed already), INVALID, CHANGED (not the bytes that were checked, or not
    ``expected`` — the record reviewed when the command started; it stays pending for fresh review) or
    STORE_ERROR. Finish with :func:`release_claim` or :func:`restore_claim`."""
    src, claim = f"{pending_id}.json", f"{pending_id}{_CLAIM_SUFFIX}"
    _pending_path(subsystem, pending_id)  # validates the id
    try:
        with _store_lock(subsystem) as st:
            if st is None or not st.lexists(src):
                return (BUSY if st is not None and st.lexists(claim) else MISSING), None
            if st.lexists(claim):
                return BUSY, None
            checked, before = st.read(src, subsystem, pending_id)
            if checked is None:
                return INVALID, None
            if expected is not None and checked != expected:
                return CHANGED, None
            try:
                st.move_no_replace(src, claim)
            except _Changed:
                return CHANGED, None
            record, after = st.read(claim, subsystem, pending_id)
            if record == checked and after == before:
                return CLAIMED, record
            try:  # replaced between the check and the claim: hand it back for fresh review
                st.move_no_replace(claim, src)
            except (OSError, _Changed):
                logger.warning("write_approval: could not hand back %s/%s", subsystem, pending_id, exc_info=True)
                return BUSY, None
            return CHANGED, None
    except FileExistsError:
        return BUSY, None
    except FileNotFoundError:
        return MISSING, None
    except PendingStoreError:
        raise  # the whole store is unusable right now: the command reports it once and stops
    except OSError:
        logger.warning("write_approval: could not claim %s/%s", subsystem, pending_id, exc_info=True)
        return STORE_ERROR, None


def release_claim(subsystem: str, pending_id: str) -> bool:
    """Drop the claim of a record that was applied. False when the claim file could not be removed
    (it then stays, listed for reconciliation, and is never re-applied)."""
    try:
        with _store_lock(subsystem) as st:
            if st is None:
                return False
            st.unlink(f"{pending_id}{_CLAIM_SUFFIX}")
        return True
    except OSError:
        logger.warning("write_approval: could not remove the claim on %s/%s", subsystem, pending_id, exc_info=True)
        return False


def restore_claim(subsystem: str, pending_id: str) -> bool:
    """Put a claimed record back in the queue after a confirmed no-effect failure. Never replaces a
    record that took its name meanwhile: False keeps the claim for reconciliation."""
    try:
        with _store_lock(subsystem) as st:
            if st is None:
                return False
            st.move_no_replace(f"{pending_id}{_CLAIM_SUFFIX}", f"{pending_id}.json")
        return True
    except (OSError, _Changed):
        logger.warning("write_approval: could not restore the claim on %s/%s", subsystem, pending_id, exc_info=True)
        return False


def discard_pending(subsystem: str, pending_id: str) -> str:
    """Delete a pending record (valid or not, so a broken one can be rejected; a symlink is removed,
    never followed): DISCARDED, MISSING, BUSY (claimed: left for whoever reconciles it) or STORE_ERROR.
    A store that is redirected or stays locked raises :class:`PendingStoreError`."""
    if not is_pending_id(pending_id):
        return MISSING
    try:
        with _store_lock(subsystem) as st:
            if st is None:
                return MISSING
            if st.lexists(f"{pending_id}{_CLAIM_SUFFIX}"):
                return BUSY
            st.unlink(f"{pending_id}.json")
            return DISCARDED
    except FileNotFoundError:
        return MISSING
    except PendingStoreError:
        raise
    except OSError as e:
        logger.error("Failed to discard pending %s/%s: %s", subsystem, pending_id, e)
        return STORE_ERROR


# --- Write origin ---

def current_origin() -> str:
    """``foreground`` or ``background_review`` — reuses the skill-provenance ContextVar
    the background review fork sets; foreground turns leave it at the default."""
    with suppress(Exception):
        from tools.skill_provenance import get_current_write_origin
        return get_current_write_origin()
    return "foreground"


# --- Gate decision ---

@dataclass(slots=True, kw_only=True)
class GateDecision:
    """Result of evaluating the write gate; exactly one flag is True. ``allow``: do the real write;
    ``blocked``: user denied the inline prompt (``message`` says why); ``stage``: caller must
    ``stage_write`` the payload (``message`` is the user-facing "staged for approval" note)."""

    allow: bool = False
    blocked: bool = False
    stage: bool = False
    message: str = ""


def _slash_review_surface() -> bool:
    """Whether the ACTIVE turn has a human who can type ``/<subsystem> pending``: the interactive
    CLI, TUI/desktop (exec route), and chat-gateway sessions all answer it now. Headless worker
    contexts — cron (``HERMES_CRON_SESSION``), kanban (``HERMES_KANBAN_TASK``) and the unattended
    programmatic platforms (api_server, webhook delivery) — have nobody at a prompt, so the staged
    hint must not name a command nobody can deliver (#98330); it names the pending dir instead."""
    def _env(name: str) -> str:
        try:
            from gateway.session_context import get_session_env
            return get_session_env(name, "") or ""
        except Exception:  # standalone/tests: process env is the fallback
            return os.environ.get(name, "") or ""
    if _env("HERMES_KANBAN_TASK").strip():
        return False
    try:
        from utils import is_truthy_value
        if is_truthy_value(_env("HERMES_CRON_SESSION")):
            return False
    except Exception:
        pass
    platform = (_env("HERMES_SESSION_PLATFORM") or os.environ.get("HERMES_PLATFORM", "")).strip().lower()
    return platform not in {"webhook", "msgraph_webhook", "api_server"}


def _staged(subsystem: str) -> GateDecision:
    command = f"/{subsystem} pending"
    if _slash_review_surface():
        where = f"review with {command}"
    else:
        where = (f"pending records live in {get_hermes_home() / 'pending' / subsystem} "
                 f"(review from an interactive CLI session with {command})")
    return GateDecision(stage=True, message=(f"Staged for approval ({subsystem}.write_approval is on). "
                                             f"Not yet saved — {where}."))


def evaluate_gate(subsystem: str, *, inline_summary: str = "", inline_detail: str = "") -> GateDecision:
    """Decide what to do with a pending write: gate off → allow; gate on + skills (any origin) or
    background → stage; gate on + memory + foreground → inline prompt when an interactive channel
    exists, else stage. The gate only ever delays a write, never silently refuses it; ``blocked``
    is produced only when the user actively denies the inline prompt."""
    if not write_approval_enabled(subsystem):
        return GateDecision(allow=True)
    # Skills are too big to review inline; a background write runs in a daemon thread with no user.
    if subsystem == SKILLS or current_origin() == "background_review":
        return _staged(subsystem)
    granted = _prompt_inline_memory_approval(inline_summary, inline_detail)
    if granted is None:
        return _staged(MEMORY)
    if granted:
        return GateDecision(allow=True)
    return GateDecision(blocked=True, message="Memory write denied by user. The change was not saved.")


def _prompt_inline_memory_approval(summary: str, detail: str) -> Optional[bool]:
    """Prompt inline for a memory write: True approved, False denied, None → stage. Uses the per-thread
    CLI approval callback (``tools.terminal_tool.set_approval_callback``) directly, not
    ``prompt_dangerous_approval``: that wrapper falls back to ``input()`` (deadlock-prone under
    prompt_toolkit; silent deny in gateway sessions) and turns callback errors into a deny, whereas
    here a missing channel or failed prompt must stage instead.

    ``hermes chat -q`` (and so every kanban worker), cron and unattended platforms can register a callback too,
    but nobody answers it: stage at once instead of waiting the approval timeout. See #15216.
    """
    from tools.approval_context import _no_user_can_answer
    if _no_user_can_answer():
        return None
    try:
        from tools.terminal_tool import _get_approval_callback
    except Exception:
        return None
    callback = _get_approval_callback()
    if callback is None:
        return None
    header = summary.strip() or "Save to memory?"
    try:
        from tools.approval_prompt import callback_accepts
        extra = {"title": "Save to memory?"} if callback_accepts(callback, "title") else {}
        choice = callback(detail.strip() or header, f"Save to memory: {header}", allow_permanent=False, **extra)
    except Exception as e:
        logger.error("Inline memory approval prompt failed: %s", e)
        return None
    # unknown outcome → stage rather than drop
    return {"once": True, "session": True, "deny": False}.get(choice)


# --- Skill-specific helpers (gist + diff for the review affordances) ---

_GIST_TEMPLATES = {"write_file": "write {file_path} in '{name}'", "remove_file": "remove {file_path} from '{name}'",
                   "delete": "delete skill '{name}'"}


def skill_gist(action: str, name: str, *, content: str = "", file_path: str = "",
               old_string: str = "", new_string: str = "") -> str:
    """One-line heuristic gist (no model call) for a pending skill write: create/edit use
    the frontmatter ``description:``; patch/write_file describe the size of the change."""
    if action in {"create", "edit"} and content:
        desc = _frontmatter_description(content)
        size = f"{len(content) // 1024 + 1} KB" if len(content) >= 1024 else f"{len(content)} chars"
        return f"{'create' if action == 'create' else 'rewrite'} '{name}'{f' — {desc}' if desc else ''} ({size})"
    if action == "patch":
        removed = old_string.count("\n") + 1 if old_string else 0
        added = new_string.count("\n") + 1 if new_string else 0
        return f"patch '{name}' {file_path or 'SKILL.md'} (+{added}/-{removed} lines)"
    return _GIST_TEMPLATES.get(action, "{action} '{name}'").format(action=action, name=name, file_path=file_path)


def _frontmatter_description(content: str) -> str:
    """Extract the ``description:`` value from SKILL.md YAML frontmatter (≤140 chars)."""
    m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip().strip("'\"")[:140] if m else ""


def _find_skill_path(name: str) -> Optional[Path]:
    """Directory of an installed skill, or None if unknown / lookup unavailable."""
    try:
        from tools.skill_manager_tool import _find_skill
    except Exception:
        return None
    # Only the import is guarded (as on main); a lookup failure propagates.
    found = _find_skill(name)
    return found["path"] if found else None


def _staged_base(name: str, target_label: str, staged: Optional[dict[str, dict[str, str]]]) -> str:
    """What an op diffs against: the content earlier ops of the same batch left in this file,
    else the on-disk copy (empty for a file that does not exist yet)."""
    files = (staged or {}).get(name)
    if files and target_label in files:
        return files[target_label]
    skill_dir = _find_skill_path(name)
    if not skill_dir:
        return ""
    with suppress(Exception):
        p = skill_dir / target_label
        if p.exists():
            return p.read_text(encoding="utf-8-sig")
    return ""


def skill_pending_diff(
    record: dict[str, Any], staged: Optional[dict[str, dict[str, str]]] = None
) -> str:
    """Full content (create) or unified diff vs. the base file (edit/patch/write_file),
    rendered by /skills diff <id> on surfaces that can show it. ``staged`` carries the file
    contents the earlier ops of a batch left behind, so op *i* diffs against ops 1..*i-1* and
    disk is read only for files no earlier op touched. A staged batch renders each op's diff
    under its gist header (single-op path below is unchanged)."""
    payload = record.get("payload", {})
    action = payload.get("action", "")
    name = payload.get("name", "")
    if action == "batch":
        return _batch_pending_diff(payload)
    if action == "create":
        return payload.get("content") or ""
    if action not in {"edit", "patch", "write_file"}:
        return {"remove_file": f"remove file: {payload.get('file_path')} from skill '{name}'",
                "delete": f"delete skill '{name}'"}.get(action, f"({action} on '{name}')")

    # patch/write_file target a file inside the skill; edit always targets SKILL.md.
    target_label = "SKILL.md" if action == "edit" else (payload.get("file_path") or "SKILL.md")
    current = _staged_base(name, target_label, staged)

    if action == "patch":
        old_s, new_s = payload.get("old_string") or "", payload.get("new_string") or ""
        if not current:
            new = f"(patch {old_s!r} → {new_s!r})"
        else:
            # Fold through the same matcher approve will run, so the preview can't
            # fabricate a result the approve path would reject (repeated anchor without
            # replace_all, whitespace-only anchor, escape drift, old_string == new_string).
            folded, patch_err = _fold_patch(current, old_s, new_s, payload.get("replace_all"))
            if patch_err:
                return f"(patch would fail: {patch_err})"
            new = folded
    else:
        new = payload.get("content" if action == "edit" else "file_content") or ""
    diff = difflib.unified_diff(current.splitlines(keepends=True), new.splitlines(keepends=True),
                                fromfile=f"a/{target_label}", tofile=f"b/{target_label}")
    return "".join(diff) or "(no textual change)"


def _fold_patch(base: str, old_string: str, new_string: str, replace_all: Any = False
                ) -> tuple[str, Optional[str]]:
    """Fold one patch op through ``fuzzy_find_and_replace`` — the SAME matcher the approve
    path runs (``_patch_skill`` / ``apply_skill_pending``) — so a previewed diff is exactly
    what an approval would commit, and a patch approval would reject (repeated anchor with
    ``replace_all`` unset, whitespace-only anchor, escape drift, ``old_string == new_string``)
    renders as an explicit failed-patch note instead of a fabricated folded result.

    Returns ``(folded_content, None)`` or ``(base, error)``; base is returned unchanged on
    error so the caller can still render the unchanged content, matching the engine's own
    ``(content, 0, None, error)`` contract. Local import: keeps write_approval importable
    without the tool chain (fuzzy_match is core-adjacent but guarded for safety anyway).
    """
    from tools.fuzzy_match import fuzzy_find_and_replace
    folded, match_count, _strategy, error = fuzzy_find_and_replace(
        base, old_string, str(new_string), bool(replace_all))
    if error or match_count == 0:
        return base, error or "Could not find a match for old_string in the file"
    return folded, None


def _fold_staged(staged: dict[str, dict[str, str]], action: str, name: str,
                 op: dict[str, Any]) -> None:
    """Record what one op leaves in the staged view the next op diffs against."""
    if not name:
        return
    if action == "delete":
        staged.pop(name, None)
        return
    label = "SKILL.md" if action == "edit" else (op.get("file_path") or "SKILL.md")
    files = staged.setdefault(name, {})
    if action in {"create", "edit"}:
        files["SKILL.md"] = op.get("content") or ""
    elif action == "write_file":
        files[label] = op.get("file_content") or ""
    elif action == "patch":
        base = _staged_base(name, label, staged)
        folded, patch_err = _fold_patch(base, op.get("old_string") or "",
                                        op.get("new_string") or "", op.get("replace_all"))
        if patch_err is None:
            files[label] = folded
        # On error the staged label keeps its prior content: approve would abort the batch
        # at this op, so nothing later in the preview should diff against a folded result
        # that will never be committed.
    elif action == "remove_file":
        files.pop(label, None)


def _batch_pending_diff(payload: dict[str, Any]) -> str:
    """Per-op diffs for a staged ``batch`` payload (skill_manage operations[]). Ops apply in
    order, so each op reuses the single-op path above with the earlier ops' staged content as
    its base (disk only for files no earlier op touched) — a patch to a skill an earlier op
    created shows a real diff, which is the case this renderer exists for."""
    ops = [op for op in (payload.get("operations") or []) if isinstance(op, dict)]
    total = len(ops)
    staged: dict[str, dict[str, str]] = {}
    parts = []
    for i, op in enumerate(ops):
        op_action, op_name = op.get("action", ""), op.get("name") or ""
        gist = skill_gist(op_action, op_name, content=op.get("content") or "",
                          file_path=op.get("file_path") or "",
                          old_string=op.get("old_string") or "",
                          new_string=op.get("new_string") or "")
        diff = skill_pending_diff({"payload": {**op, "name": op_name}}, staged)
        parts.append(f"## op {i + 1}/{total}: {gist}\n\n{diff}")
        _fold_staged(staged, op_action, op_name, op)
    return "\n\n".join(parts) or "(empty batch)"
