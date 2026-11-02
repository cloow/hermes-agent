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


# ── 1. approve vs reject ─────────────────────────────────────────────────────

def test_approve_and_reject_of_one_id_never_both_succeed(home, monkeypatch):
    pid = _stage_skill("contested")
    real_link, replies, fired = os.link, {}, []

    def link_then_reject(src, dst, *a, **k):
        real_link(src, dst, *a, **k)
        if not fired:  # a second surface rejects the id while the approval is moving it
            fired.append(1)
            t = threading.Thread(target=lambda: replies.setdefault("reject", _skills(f"reject {pid}")))
            t.start()
            t.join(timeout=2)
            replies["thread"] = t

    monkeypatch.setattr(os, "link", link_then_reject)
    out = _skills(f"approve {pid}")
    replies["thread"].join(timeout=30)
    approved = f"{pid}: approved" in out
    rejected = "Rejected pending" in replies["reject"]
    assert approved != rejected, f"exactly one may win:\n{out}\n{replies['reject']}"
    assert (home / "skills" / "contested").exists() == approved


# ── 2. the claim is bound to the checked record ──────────────────────────────

def test_record_swapped_during_the_claim_goes_back_for_fresh_review(home, monkeypatch):
    pid = _stage_skill("reviewed")
    real_link, swapped = os.link, []

    def swap_then_link(src, dst, *a, **k):
        if not swapped and str(src).endswith(f"{pid}.json"):
            swapped.append(1)
            _rewrite_valid(home, pid, "swapped-in")
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", swap_then_link)
    out = _skills(f"approve {pid}")
    assert not (home / "skills" / "swapped-in").exists(), out
    assert f"{pid}: changed" in out and "Approved 0" in out, out
    assert json.loads((_store(home) / f"{pid}.json").read_text())["payload"]["name"] == "swapped-in"
    assert not (_store(home) / f"{pid}.applying.json").exists()


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

@pytest.mark.parametrize("where", ["release_claim", "claim_pending"])
def test_an_interrupt_anywhere_reports_what_finished(home, monkeypatch, where):
    first, second, third = _stage_skill("ki-a"), _stage_skill("ki-b"), _stage_skill("ki-c")
    real = getattr(wa, where)

    def interrupt_on_second(subsystem, pending_id, *a, **k):
        if pending_id == second:
            raise KeyboardInterrupt
        return real(subsystem, pending_id, *a, **k)

    monkeypatch.setattr(wa, where, interrupt_on_second)
    out = _skills(f"approve {first} {second} {third}")
    assert f"{first}: approved" in out and f"{second}: interrupted" in out, out
    assert f"{third}: not attempted" in out
    assert "Approved 1 skills write(s)." in out and "3 selected:" in out
    assert not (home / "skills" / "ki-c").exists()


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
