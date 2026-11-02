"""Pending-store races and ambiguous outcomes around the approval claim (tools/write_approval.py).

An approve and a reject of one id never both succeed; a claim is bound to the record that was
checked (a changed record goes back for fresh review); a store redirected by a link is refused;
only an explicit, confirmed applier failure puts a claimed record back; an interrupt anywhere in a
batch still reports what finished; a claimed id is never listed, counted or bulk-rejected as
pending; and a locked skill stays protected inside a batch. Temp HERMES_HOME, fake records.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path

import pytest

from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools import write_approval as wa

_SKILL = "---\nname: {name}\ndescription: race test {name}\n---\n\n# {name}\n\nBody.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    h.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def _store(home) -> Path:
    return home / "pending" / "skills"


def _stage_skill(name: str, content: str | None = None) -> str:
    return wa.stage_write(wa.SKILLS, {"action": "create", "name": name, "content": content or _SKILL.format(name=name)},
                          summary=f"create {name}", origin="foreground")["id"]


def _skills(args: str) -> str:
    return handle_pending_subcommand(wa.SKILLS, args.split())


def _patch_applier(monkeypatch, fn):
    import tools.skill_manager_tool as smt
    monkeypatch.setattr(smt, "apply_skill_pending", fn)


def _rewrite_valid(home, pid: str, name: str) -> None:
    """Replace ``<id>.json`` (new inode, still a well-formed record) with a different write."""
    path = _store(home) / f"{pid}.json"
    rec = json.loads(path.read_text())
    rec["payload"] = {"action": "create", "name": name, "content": _SKILL.format(name=name)}
    tmp = path.with_name("swap.tmp")
    tmp.write_text(json.dumps(rec))
    os.replace(tmp, path)


# ── 1. approve vs reject, and a source replaced mid-move ─────────────────────
# "rename": the atomic no-replace rename (renameat2 / renameatx_np) — hook just before it runs.
# "link": the hard-link fallback (no such rename here) — hook between the link and the unlink.

def _hook_move(monkeypatch, path: str, pid: str, hook) -> None:
    fired = []

    def once():
        if not fired:
            fired.append(1)
            hook()

    if path == "rename":
        real = wa._renameat_noreplace

        def renamed(dir_fd, src, dst):
            if src == f"{pid}.json":
                once()
            return real(dir_fd, src, dst)

        monkeypatch.setattr(wa, "_renameat_noreplace", renamed, raising=False)
    else:
        real_link = os.link
        monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)

        def linked(src, dst, *a, **k):
            real_link(src, dst, *a, **k)
            if str(src).endswith(f"{pid}.json"):
                once()

        monkeypatch.setattr(os, "link", linked)


@pytest.mark.parametrize("path", ["rename", "link"])
def test_approve_and_reject_of_one_id_never_both_succeed(home, monkeypatch, path):
    pid = _stage_skill("contested")
    replies, threads = {}, []

    def reject_from_another_surface():  # started mid-claim, never joined while the claim holds the lock
        t = threading.Thread(target=lambda: replies.setdefault("reject", _skills(f"reject {pid}")))
        t.start()
        threads.append(t)

    _hook_move(monkeypatch, path, pid, reject_from_another_surface)
    out = _skills(f"approve {pid}")
    threads[0].join()
    assert f"{pid}: approved" in out, out
    assert "Rejected pending" not in replies["reject"], replies["reject"]
    assert (home / "skills" / "contested").exists()


@pytest.mark.parametrize("path", ["rename", "link"])
def test_a_source_replaced_mid_move_goes_back_for_fresh_review(home, monkeypatch, path):
    pid = _stage_skill("reviewed")
    _hook_move(monkeypatch, path, pid, lambda: _rewrite_valid(home, pid, "swapped-in"))
    out = _skills(f"approve {pid}")
    assert not (home / "skills" / "reviewed").exists() and not (home / "skills" / "swapped-in").exists(), out
    assert f"{pid}: changed" in out and "Approved 0" in out, out
    assert json.loads((_store(home) / f"{pid}.json").read_text())["payload"]["name"] == "swapped-in"
    assert not (_store(home) / f"{pid}.applying.json").exists()


def test_explicit_ids_apply_only_what_was_selected(home, monkeypatch):
    import tools.skill_manager_tool as smt
    first, second = _stage_skill("sel-first"), _stage_skill("sel-second")
    real = smt.apply_skill_pending

    def applier(payload):
        if payload["name"] == "sel-first":  # while id1 applies, id2 is rewritten under the approver
            _rewrite_valid(home, second, "unreviewed-swap")
        return real(payload)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {first} {second}")
    assert f"{first}: approved" in out and f"{second}: changed" in out and "Approved 1" in out, out
    assert not (home / "skills" / "unreviewed-swap").exists()
    assert [r["payload"]["name"] for r in wa.list_pending(wa.SKILLS)] == ["unreviewed-swap"]


def test_an_id_absent_when_the_command_started_stays_not_pending(home, monkeypatch):
    import tools.skill_manager_tool as smt
    first = _stage_skill("early")
    late = "0badc0de" if first != "0badc0de" else "deadbeef"
    real = smt.apply_skill_pending

    def applier(payload):
        rec = json.loads((_store(home) / f"{first}.applying.json").read_text())
        rec.update(id=late, payload={"action": "create", "name": "late", "content": _SKILL.format(name="late")})
        (_store(home) / f"{late}.json").write_text(json.dumps(rec))
        return real(payload)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {first} {late}")
    assert f"{late}: not pending" in out and not (home / "skills" / "late").exists(), out


def test_approve_all_applies_only_the_records_it_listed(home, monkeypatch):
    pid = _stage_skill("listed")
    real_claim = wa.claim_pending

    def change_then_claim(subsystem, pending_id, *a, **k):
        _rewrite_valid(home, pending_id, "after-listing")
        return real_claim(subsystem, pending_id, *a, **k)

    monkeypatch.setattr(wa, "claim_pending", change_then_claim)
    out = _skills("approve all")
    assert not (home / "skills" / "after-listing").exists(), out
    assert f"{pid}: changed" in out, out


# ── 3. redirected store ──────────────────────────────────────────────────────

@pytest.mark.platforms("posix")
@pytest.mark.parametrize("link_at", ["pending", "pending/skills"])
def test_a_store_redirected_by_a_link_is_refused(home, tmp_path, link_at):
    pid = _stage_skill("elsewhere")
    outside = tmp_path / "outside"
    real = home / link_at
    real.rename(outside)
    real.symlink_to(outside, target_is_directory=True)
    out = _skills(f"approve {pid}")
    assert "Refusing to use the skills pending store" in out, out
    assert not (home / "skills" / "elsewhere").exists()
    assert not list(outside.rglob("*.applying.json")), "no claim may be made in the redirected directory"
    assert "Refusing" in _skills(f"reject {pid}") and list(outside.rglob(f"{pid}.json"))
    assert "Refusing" in _skills("pending")


# ── 4. ambiguous applier outcomes ────────────────────────────────────────────

@pytest.mark.parametrize("result", [{}, {"success": False}, {"success": None, "error": "x"}, {"success": "yes"}])
def test_an_unclear_outcome_keeps_the_claim(home, monkeypatch, result):
    pid = _stage_skill("unclear")
    calls = []

    def applier(payload):
        calls.append(1)
        return json.dumps(result)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert f"{pid}: outcome uncertain" in out and "Approved 0" in out, out
    assert (_store(home) / f"{pid}.applying.json").exists() and not (_store(home) / f"{pid}.json").exists()
    assert f"{pid}: busy" in _skills(f"approve {pid}") and calls == [1], "never replayed"


# ── 5. interrupts outside the applier ────────────────────────────────────────

def _interrupt_on(monkeypatch, where: str, target: str) -> None:
    real = getattr(wa, where)

    def interrupt(subsystem, pending_id, *a, **k):
        if pending_id == target:
            raise KeyboardInterrupt
        return real(subsystem, pending_id, *a, **k)

    monkeypatch.setattr(wa, where, interrupt)


def test_an_interrupt_while_claiming_reports_what_finished(home, monkeypatch):
    first, second, third = _stage_skill("ki-a"), _stage_skill("ki-b"), _stage_skill("ki-c")
    _interrupt_on(monkeypatch, "claim_pending", second)
    out = _skills(f"approve {first} {second} {third}")
    assert f"{first}: approved" in out and f"{second}: interrupted" in out, out
    assert f"{third}: not attempted" in out
    assert "Approved 1 skills write(s)." in out and "3 selected:" in out
    assert not (home / "skills" / "ki-b").exists() and not (home / "skills" / "ki-c").exists()


def test_an_interrupt_after_a_successful_apply_reports_it_applied(home, monkeypatch):
    first, second, third = _stage_skill("ka-a"), _stage_skill("ka-b"), _stage_skill("ka-c")
    _interrupt_on(monkeypatch, "release_claim", second)
    out = _skills(f"approve {first} {second} {third}")
    assert "Approved 2 skills write(s)." in out, out
    assert f"{first}: approved" in out and f"{second}: applied; interrupted" in out
    assert f"{third}: not attempted" in out and not (home / "skills" / "ka-c").exists()
    assert (home / "skills" / "ka-b").is_dir() and (_store(home) / f"{second}.applying.json").exists()


def test_an_interrupted_memory_cleanup_keeps_the_changed_entry_notice(home, monkeypatch):
    from tools.memory_tool import MemoryStore
    store = MemoryStore()
    store.load_from_disk()
    handle_pending_subcommand(wa.MEMORY, ["approve", wa.stage_write(
        wa.MEMORY, {"action": "add", "target": "user", "content": "likes tea and biscuits"},
        summary="add", origin="foreground")["id"]], memory_store=store)
    from tools.memory_tool import memory_tool
    import hermes_cli.config as cfg
    c = cfg.load_config()
    c.setdefault("memory", {})["write_approval"] = True
    cfg.save_config(c)
    staged = json.loads(memory_tool("patch", "user", "coffee", old_text="tea", store=store))
    pid = staged.get("pending_id")
    assert pid, staged
    _interrupt_on(monkeypatch, "release_claim", pid)
    out = handle_pending_subcommand(wa.MEMORY, ["approve", pid], memory_store=store)
    assert "Approved 1 memory write(s)." in out and "likes tea and biscuits" in out, out


# ── 4b. oversized and non-positive timestamps ────────────────────────────────

@pytest.mark.parametrize("bad", [10 ** 400, 0, -5])
def test_an_unusable_timestamp_is_invalid_and_does_not_stop_the_batch(home, bad):
    broken, fine = _stage_skill("ts-broken"), _stage_skill("ts-fine")
    path = _store(home) / f"{broken}.json"
    rec = json.loads(path.read_text())
    rec["created_at"] = bad
    path.write_text(json.dumps(rec))
    assert wa.get_pending(wa.SKILLS, broken) is None
    out = _skills(f"approve {broken} {fine}")
    assert f"{broken}: invalid record" in out and f"{fine}: approved" in out, out
    assert (broken, "invalid") in wa.list_unapprovable(wa.SKILLS)


# ── 5b. reject reports what really happened ──────────────────────────────────

def test_reject_of_an_id_claimed_after_a_stale_check_says_claimed(home, monkeypatch):
    pid = _stage_skill("claimed-late")
    os.link(_store(home) / f"{pid}.json", _store(home) / f"{pid}.applying.json")
    monkeypatch.setattr(wa, "is_claimed", lambda *a: False)  # an unlocked check that ran too early
    out = _skills(f"reject {pid}")
    assert "not rejected" in out and "No pending" not in out, out
    assert (_store(home) / f"{pid}.json").exists()


@pytest.mark.parametrize("args", ["reject {pid}", "reject all"])
def test_reject_reports_a_locked_store_instead_of_nothing_pending(home, monkeypatch, args):
    pid = _stage_skill("lock-timeout")

    def timed_out(*a, **k):
        raise wa.PendingStoreError("Timed out waiting for the skills pending store")

    monkeypatch.setattr(wa, "_store_lock", timed_out)
    out = _skills(args.format(pid=pid))
    assert "Timed out waiting" in out and "No pending" not in out and "Rejected 0" not in out, out
    assert (_store(home) / f"{pid}.json").exists()


# ── 6b. no store directories conjured for a deleted profile ──────────────────

@pytest.mark.parametrize("args", ["reject 0badc0de", "approve 0badc0de", "reject all", "approve all"])
def test_review_of_a_profile_without_a_store_creates_nothing(tmp_path, monkeypatch, args):
    gone = tmp_path / "deleted-profile"
    monkeypatch.setenv("HERMES_HOME", str(gone))
    _skills(args)
    assert not gone.exists(), sorted(str(p) for p in gone.rglob("*"))


# ── 7b. the store directory is pinned across the lock ────────────────────────

def _swap_store_for_link(home, outside) -> None:
    _store(home).rename(home / "pending" / "skills.moved")
    _store(home).symlink_to(outside, target_is_directory=True)


@pytest.mark.platforms("posix")
@pytest.mark.parametrize("when", ["before_open", "after_open"])
def test_a_store_swapped_for_a_link_after_the_check_is_not_used(home, tmp_path, monkeypatch, when):
    from hermes_cli import auth
    pid = _stage_skill("pinned")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / f"{pid}.json").write_text((_store(home) / f"{pid}.json").read_text())
    swapped = []

    def swap_once():
        if not swapped:
            swapped.append(1)
            _swap_store_for_link(home, outside)

    if when == "before_open":  # between the path check and opening the store (also where a lock file was opened)
        real_dir, real_lock = wa._pending_dir, auth._file_lock

        def checked_then_swapped(subsystem):
            d = real_dir(subsystem)
            swap_once()
            return d

        monkeypatch.setattr(wa, "_pending_dir", checked_then_swapped)
        monkeypatch.setattr(auth, "_file_lock", lambda *a, **k: (swap_once(), real_lock(*a, **k))[1])
    else:  # the store was opened, then swapped before the lock was taken
        real_flock = getattr(wa, "_flock_with_deadline", None)
        monkeypatch.setattr(wa, "_flock_with_deadline", lambda fd, s: (swap_once(), real_flock(fd, s)), raising=False)
    out = _skills(f"approve {pid}")
    assert not list(outside.glob("*.applying.json")) and (outside / f"{pid}.json").exists(), out
    assert not (outside / ".store.lock").exists(), "nothing may be created through the link"
    assert not (home / "skills" / "pinned").exists() and "Approved 0" in out, out
    assert "pending store" in out, out


# ── round 3: the lock itself ─────────────────────────────────────────────────

@pytest.mark.platforms("posix")
def test_a_lock_file_link_is_never_followed(home):
    pid = _stage_skill("lock-link")
    victim = home / "auth.json"
    victim.write_text('{"keep": "me"}')
    (_store(home) / ".store.lock").unlink(missing_ok=True)
    (_store(home) / ".store.lock").symlink_to(victim)
    out = _skills(f"approve {pid}")
    assert f"{pid}: approved" in out, out
    assert victim.read_text() == '{"keep": "me"}', "the link target must be untouched"


@pytest.mark.parametrize("when", ["after_check", "before_lock"])
def test_a_profile_deleted_before_the_lock_stays_deleted(tmp_path, monkeypatch, when):
    import shutil

    from hermes_cli import auth
    gone = tmp_path / "doomed-profile"
    monkeypatch.setenv("HERMES_HOME", str(gone))
    _stage_skill("doomed")

    def delete():
        shutil.rmtree(gone, ignore_errors=True)

    if when == "before_lock":  # removed just before the lock is taken (a path-based lock file would mkdir)
        real_lock, real_flock = auth._file_lock, getattr(wa, "_flock_with_deadline", None)
        monkeypatch.setattr(auth, "_file_lock", lambda *a, **k: (delete(), real_lock(*a, **k))[1])
        monkeypatch.setattr(wa, "_flock_with_deadline", lambda fd, s: (delete(), real_flock(fd, s)), raising=False)
    else:  # removed right after the store path was checked
        real_dir = wa._pending_dir
        monkeypatch.setattr(wa, "_pending_dir", lambda subsystem: (real_dir(subsystem), delete())[0])
    _skills("reject 0badc0de")
    assert not gone.exists(), sorted(str(p) for p in gone.rglob("*"))


def test_staging_never_replaces_an_existing_record(home, monkeypatch):
    import uuid as uuid_mod
    taken = _stage_skill("first-come")
    before = (_store(home) / f"{taken}.json").read_text()
    real, forced = uuid_mod.uuid4, []

    def collide():
        if not forced:
            forced.append(1)
            return uuid_mod.UUID(taken + "0" * 24)
        return real()

    monkeypatch.setattr(uuid_mod, "uuid4", collide)
    rec = _stage_skill("second-come")
    assert rec != taken and (_store(home) / f"{taken}.json").read_text() == before
    assert {r["payload"]["name"] for r in wa.list_pending(wa.SKILLS)} == {"first-come", "second-come"}


def test_staging_publishes_under_the_store_lock(home, monkeypatch):
    _stage_skill("make-the-store")
    real_lock, seen = wa._store_lock, []

    def names():
        return {p.name for p in _store(home).glob("*.json")}

    @contextlib.contextmanager
    def watched(subsystem, *a, **k):
        with real_lock(subsystem, *a, **k) as st:
            inside = names()
            yield st
            seen.append(names() - inside)

    monkeypatch.setattr(wa, "_store_lock", watched)
    pid = _stage_skill("published-inside")
    assert {f"{pid}.json"} in seen, seen


def test_a_source_replaced_before_the_old_name_is_dropped_is_kept(home, monkeypatch):
    pid = _stage_skill("old-reviewed")
    monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)  # the hard-link fallback
    swapped, real_unlink, real_rename = [], os.unlink, os.rename

    def swap_first(real):
        def call(path, *a, **k):
            if not swapped and str(path).endswith(f"{pid}.json") and ".applying" not in str(path):
                swapped.append(1)  # an out-of-band writer replaces the source just before it is dropped
                _rewrite_valid(home, pid, "new-unreviewed")
            return real(path, *a, **k)
        return call

    monkeypatch.setattr(os, "unlink", swap_first(real_unlink))
    monkeypatch.setattr(os, "rename", swap_first(real_rename))
    out = _skills(f"approve {pid}")
    assert swapped, "the drop step was reached"
    assert not (home / "skills" / "old-reviewed").exists() and not (home / "skills" / "new-unreviewed").exists(), out
    assert f"{pid}: changed" in out and "Approved 0" in out, out
    assert json.loads((_store(home) / f"{pid}.json").read_text())["payload"]["name"] == "new-unreviewed"
    assert not (_store(home) / f"{pid}.applying.json").exists()


def test_restore_without_atomic_primitives_never_overwrites_a_staged_record(home, monkeypatch):
    import uuid as uuid_mod
    pid = _stage_skill("restored")
    original = (_store(home) / f"{pid}.json").read_text()
    monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)

    def no_links(*a, **k):
        raise PermissionError("no hard links on this filesystem")

    monkeypatch.setattr(os, "link", no_links)
    real_rename, real_uuid, threads, forced = os.rename, uuid_mod.uuid4, [], []

    def collide():
        if not forced:
            forced.append(1)
            return uuid_mod.UUID(pid + "0" * 24)
        return real_uuid()

    def rename(src, dst, *a, **k):
        if str(src).endswith(f"{pid}.applying.json") and not threads:  # the restore: another surface stages now
            monkeypatch.setattr(uuid_mod, "uuid4", collide)
            t = threading.Thread(target=lambda: _stage_skill("newcomer-to-preserve"))
            t.start()
            threads.append(t)
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", rename)
    _patch_applier(monkeypatch, lambda payload: json.dumps({"success": False, "error": "nope"}))
    out = _skills(f"approve {pid}")
    threads[0].join()
    assert f"{pid}: failed (nope); left pending" in out, out
    assert (_store(home) / f"{pid}.json").read_text() == original
    assert {r["payload"]["name"] for r in wa.list_pending(wa.SKILLS)} == {"restored", "newcomer-to-preserve"}


# ── round 3: a busy store stops the batch once; locks are per store ─────────

def test_a_store_lock_timeout_stops_the_batch_once(home, monkeypatch):
    first, second, third = _stage_skill("to-a"), _stage_skill("to-b"), _stage_skill("to-c")
    real_lock, calls = wa._store_lock, []

    def lock(subsystem, *a, **k):
        calls.append(1)
        if len(calls) >= 3:  # id1 claim + release took it; id2's claim times out
            raise wa.PendingStoreError("Timed out waiting for the skills pending store")
        return real_lock(subsystem, *a, **k)

    monkeypatch.setattr(wa, "_store_lock", lock)
    out = _skills(f"approve {first} {second} {third}")
    assert f"{first}: approved" in out and f"{second}: not applied — Timed out" in out, out
    assert f"{third}: not attempted" in out and len(calls) == 3, (out, len(calls))


def test_holding_one_stores_lock_does_not_unlock_another(home, tmp_path, monkeypatch):
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setattr(wa, "_LOCK_TIMEOUT_S", 0.2, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(other))
    theirs = _stage_skill("theirs")
    monkeypatch.setenv("HERMES_HOME", str(home))
    _stage_skill("ours")
    result = {}
    with wa._store_lock(wa.SKILLS):
        monkeypatch.setenv("HERMES_HOME", str(other))
        with wa._store_lock(wa.SKILLS):  # same thread, another profile's store: must really lock it too

            def probe():  # runs with HERMES_HOME=other (process env)
                try:
                    result["state"] = wa.discard_pending(wa.SKILLS, theirs)
                except wa.PendingStoreError as e:
                    result["error"] = str(e)

            t = threading.Thread(target=probe)
            t.start()
            t.join()
    assert "error" in result and "Timed out" in result["error"], result
    assert (other / "pending" / "skills" / f"{theirs}.json").exists()


# ── 6. a claimed id is not pending ───────────────────────────────────────────

def test_a_record_that_reappears_beside_its_claim_is_not_pending(home):
    pid = _stage_skill("reappeared")
    path = _store(home) / f"{pid}.json"
    claim = _store(home) / f"{pid}.applying.json"
    os.link(path, claim)  # an interrupted approval's claim, and the record back under its own name
    assert wa.list_pending(wa.SKILLS) == [] and wa.pending_count(wa.SKILLS) == 0
    assert (pid, "claimed") in wa.list_unapprovable(wa.SKILLS)
    assert _skills("approve all").startswith("No pending skills writes.")
    assert _skills("reject all") == "Rejected 0 pending skills write(s)."
    assert "not rejected" in _skills(f"reject {pid}")
    assert path.exists() and claim.exists()


def test_pending_count_counts_only_minted_unclaimed_records(home):
    pid = _stage_skill("counted")
    (_store(home) / "notes.json").write_text("{}")
    (_store(home) / "0badc0de.applying.json").write_text("{}")
    assert wa.pending_count(wa.SKILLS) == 1, sorted(p.name for p in _store(home).iterdir())
    assert [r["id"] for r in wa.list_pending(wa.SKILLS)] == [pid]


# ── 7. timestamps ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_timestamp_is_not_a_record(home, bad):
    pid = _stage_skill("forever")
    path = _store(home) / f"{pid}.json"
    rec = json.loads(path.read_text())
    rec["created_at"] = bad
    path.write_text(json.dumps(rec))
    assert wa.get_pending(wa.SKILLS, pid) is None and wa.list_pending(wa.SKILLS) == []


# ── 9. locked skills inside a batch ──────────────────────────────────────────

def test_a_locked_skill_stays_protected_in_a_batch(home):
    from tools import skill_usage
    for name in ("lock-me", "free-me"):
        _skills(f"approve {_stage_skill(name)}")
    locked, free = (wa.stage_write(wa.SKILLS, {"action": "patch", "name": n, "old_string": "Body.",
                                               "new_string": "Changed."}, summary=f"patch {n}",
                                   origin="foreground")["id"] for n in ("lock-me", "free-me"))
    assert skill_usage.set_locked("lock-me", True)
    out = _skills(f"approve {locked} {free}")
    assert f"{locked}: failed" in out and f"{free}: approved" in out, out
    assert "Body." in (home / "skills" / "lock-me" / "SKILL.md").read_text()
    assert "Changed." in (home / "skills" / "free-me" / "SKILL.md").read_text()
    assert [r["id"] for r in wa.list_pending(wa.SKILLS)] == [locked]
