"""Pending-store races and ambiguous outcomes around the approval claim (tools/write_approval.py).

An approve and a reject of one id never both succeed; a claim is bound to the record that was
checked (a changed record goes back for fresh review); a store redirected by a link is refused;
only an explicit, confirmed applier failure puts a claimed record back; an interrupt anywhere in a
batch still reports what finished; a claimed id is never listed, counted or bulk-rejected as
pending; and a locked skill stays protected inside a batch. Temp HERMES_HOME, fake records.
"""

from __future__ import annotations

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
    replies = {}

    def reject_from_another_surface():
        t = threading.Thread(target=lambda: replies.setdefault("reject", _skills(f"reject {pid}")))
        t.start()
        t.join(timeout=2)
        replies["thread"] = t

    _hook_move(monkeypatch, path, pid, reject_from_another_surface)
    out = _skills(f"approve {pid}")
    replies["thread"].join(timeout=30)
    approved = f"{pid}: approved" in out
    rejected = "Rejected pending" in replies["reject"]
    assert approved != rejected, f"exactly one may win:\n{out}\n{replies['reject']}"
    assert (home / "skills" / "contested").exists() == approved


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

@pytest.mark.platforms("posix")
def test_a_store_swapped_for_a_link_after_the_check_is_not_used(home, tmp_path, monkeypatch):
    from hermes_cli import auth
    pid = _stage_skill("pinned")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / f"{pid}.json").write_text((_store(home) / f"{pid}.json").read_text())
    real_lock, swapped = auth._file_lock, []

    def swap_then_lock(*a, **k):
        if not swapped:
            swapped.append(1)
            _store(home).rename(home / "pending" / "skills.moved")
            _store(home).symlink_to(outside, target_is_directory=True)
        return real_lock(*a, **k)

    monkeypatch.setattr(auth, "_file_lock", swap_then_lock)
    out = _skills(f"approve {pid}")
    assert not list(outside.glob("*.applying.json")) and (outside / f"{pid}.json").exists(), out
    assert not (home / "skills" / "pinned").exists() and "Approved 0" in out, out


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
