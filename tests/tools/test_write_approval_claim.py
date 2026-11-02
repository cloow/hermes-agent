"""Pending-store hardening and the per-record approval claim (tools/write_approval.py).

An approval claims ``<id>.json`` by moving it to ``<id>.applying.json`` in the same directory
before applying it, so two approvers never replay one record. A claim left behind (crash,
uncertain rollback, failed cleanup) is evidence for a human, never permission to retry: it is
listed as needing reconciliation and ``approve`` refuses it. Records are looked up only by the
minted id format, must be what their file name says, and redirected (symlinked) files are refused.
Exercised against a temp HERMES_HOME with fake records and the real appliers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools import write_approval as wa

_SKILL = "---\nname: {name}\ndescription: claim test {name}\n---\n\n# {name}\n\nBody.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    h.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def _store(home, subsystem=wa.SKILLS) -> Path:
    return home / "pending" / subsystem


def _entries(home, subsystem=wa.SKILLS) -> list[str]:
    """Record and claim files in the store (its lock file is bookkeeping)."""
    return sorted(p.name for p in _store(home, subsystem).iterdir() if p.name != ".store.lock")


def _stage_skill(name: str) -> str:
    return wa.stage_write(wa.SKILLS, {"action": "create", "name": name, "content": _SKILL.format(name=name)},
                          summary=f"create {name}", origin="foreground")["id"]


def _skills(args: str) -> str:
    return handle_pending_subcommand(wa.SKILLS, args.split())


def _patch_applier(monkeypatch, fn):
    import tools.skill_manager_tool as smt
    monkeypatch.setattr(smt, "apply_skill_pending", fn)


# ── store hardening ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "../../auth", "/etc/passwd", "a/b", "A1B2C3D4", "a1b2c3d", "a1b2c3d4e",
                                 "a1b2c3d4.applying", "a1b2c3d4.json", None, 12345678])
def test_lookups_accept_only_minted_ids(home, bad):
    victim = home / "auth.json"
    victim.write_text('{"id": "x", "payload": {}}')
    _stage_skill("hardening")
    assert wa.get_pending(wa.SKILLS, bad) is None
    assert wa.discard_pending(wa.SKILLS, bad) == wa.MISSING
    assert victim.exists()


def test_record_must_be_what_its_file_name_says(home):
    real = _stage_skill("identity-real")
    other = "0badc0de" if real != "0badc0de" else "deadbeef"
    body = json.loads((_store(home) / f"{real}.json").read_text())
    (_store(home) / f"{other}.json").write_text(json.dumps(body))  # inner id names another record
    assert wa.get_pending(wa.SKILLS, other) is None
    assert [r["id"] for r in wa.list_pending(wa.SKILLS)] == [real]
    out = _skills(f"approve {other}")
    assert f"{other}: invalid record" in out and "Approved 0" in out, out
    assert (_store(home) / f"{real}.json").exists() and (_store(home) / f"{other}.json").exists()
    assert not (home / "skills" / "identity-real").exists()
    assert f"{other}" in _skills("pending"), "an invalid record stays visible so it can be rejected"
    assert "Rejected pending skills write" in _skills(f"reject {other}")


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(subsystem="memory"),
    lambda r: r.update(payload="not an object"),
    lambda r: r.update(created_at="yesterday"),
    lambda r: r.pop("created_at"),
])
def test_malformed_record_is_not_approvable(home, mutate):
    pid = _stage_skill("shape")
    path = _store(home) / f"{pid}.json"
    rec = json.loads(path.read_text())
    mutate(rec)
    path.write_text(json.dumps(rec))
    assert wa.get_pending(wa.SKILLS, pid) is None
    out = _skills(f"approve {pid}")
    assert f"{pid}: invalid record" in out, out
    assert path.exists() and not (home / "skills" / "shape").exists()


@pytest.mark.platforms("posix")
def test_symlinked_record_is_refused(home, tmp_path):
    outside = tmp_path / "outside.json"
    pid = _stage_skill("linked")
    path = _store(home) / f"{pid}.json"
    outside.write_text(path.read_text())
    path.unlink()
    path.symlink_to(outside)
    assert wa.get_pending(wa.SKILLS, pid) is None
    assert wa.list_pending(wa.SKILLS) == []
    out = _skills(f"approve {pid}")
    assert "Approved 0" in out and not (home / "skills" / "linked").exists(), out
    assert outside.exists()


# ── the claim ────────────────────────────────────────────────────────────────

def test_second_approver_of_one_record_reports_busy_and_does_not_replay(home, monkeypatch):
    import tools.skill_manager_tool as smt
    pid = _stage_skill("raced")
    real, calls, inner = smt.apply_skill_pending, [], {}

    def applier(payload):
        calls.append(payload["name"])
        inner["out"] = _skills(f"approve {pid}")  # a second surface approves the same id mid-apply
        return real(payload)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert calls == ["raced"], "the record must be applied exactly once"
    assert f"{pid}: busy" in inner["out"] and "Approved 0" in inner["out"], inner
    assert f"{pid}: approved" in out
    assert not _entries(home), "the claim is removed after a clean apply"


def test_reject_does_not_remove_a_claimed_record(home, monkeypatch):
    import tools.skill_manager_tool as smt
    pid = _stage_skill("claimed-reject")
    real, inner = smt.apply_skill_pending, {}

    def applier(payload):
        inner["out"] = _skills(f"reject {pid}")
        return real(payload)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert f"{pid}: approved" in out and "not rejected" in inner["out"], (out, inner)


def test_confirmed_failure_restores_the_record(home, monkeypatch):
    pid = _stage_skill("restore-me")
    _patch_applier(monkeypatch, lambda payload: json.dumps({"success": False, "error": "nope"}))
    out = _skills(f"approve {pid}")
    assert f"{pid}: failed (nope); left pending" in out, out
    assert _entries(home) == [f"{pid}.json"]
    assert [r["id"] for r in wa.list_pending(wa.SKILLS)] == [pid]


def test_applier_exception_keeps_the_claim_for_reconciliation(home, monkeypatch):
    pid = _stage_skill("crashy")

    def applier(payload):
        raise RuntimeError("disk vanished")

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert f"{pid}: outcome uncertain" in out, out
    assert (_store(home) / f"{pid}.applying.json").exists() and not (_store(home) / f"{pid}.json").exists()
    _patch_applier(monkeypatch, lambda payload: pytest.fail("a leftover claim must never be retried"))
    again = _skills(f"approve {pid}")
    assert f"{pid}: busy" in again and "Approved 0" in again, again
    assert _skills("approve all").startswith("No pending skills writes."), "all never picks up a claim"
    listing = _skills("pending")
    assert pid in listing and "reconcil" in listing, listing


def test_failed_batch_rollback_keeps_the_claim(home, monkeypatch):
    pid = _stage_skill("rollback")
    _patch_applier(monkeypatch, lambda payload: json.dumps(
        {"success": False, "error": "batch aborted, ROLLBACK FAILED", "rollback_failed": True}))
    out = _skills(f"approve {pid}")
    assert f"{pid}: outcome uncertain" in out, out
    assert (_store(home) / f"{pid}.applying.json").exists()


def test_cleanup_failure_is_reported_and_never_replayed(home, monkeypatch):
    import os
    pid = _stage_skill("sticky")
    real_unlink = os.unlink

    def flaky_unlink(path, *a, **k):
        if str(path).endswith(".applying.json"):
            raise PermissionError("read-only store")
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", flaky_unlink)
    out = _skills(f"approve {pid}")
    monkeypatch.setattr(os, "unlink", real_unlink)
    assert f"{pid}: applied, but its claim file could not be removed" in out, out
    assert "Approved 1 skills write(s)." in out
    assert (home / "skills" / "sticky" / "SKILL.md").is_file()
    again = _skills(f"approve {pid}")
    assert f"{pid}: busy" in again, again


def test_restore_never_overwrites_a_record_that_appeared_meanwhile(home, monkeypatch):
    pid = _stage_skill("conflict")
    newcomer = {"id": pid, "subsystem": "skills", "action": "create", "summary": "newcomer", "origin": "foreground",
                "created_at": 1.0, "payload": {"action": "create", "name": "newcomer", "content": "x"}}

    def applier(payload):
        (_store(home) / f"{pid}.json").write_text(json.dumps(newcomer))
        return json.dumps({"success": False, "error": "nope"})

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert f"{pid}: failed" in out and "claim kept" in out, out
    assert json.loads((_store(home) / f"{pid}.json").read_text())["summary"] == "newcomer"
    assert (_store(home) / f"{pid}.applying.json").exists()


def test_interrupt_stops_before_the_next_record(home, monkeypatch):
    import tools.skill_manager_tool as smt
    first, second, third = _stage_skill("int-a"), _stage_skill("int-b"), _stage_skill("int-c")
    real = smt.apply_skill_pending

    def applier(payload):
        if payload["name"] == "int-b":
            raise KeyboardInterrupt
        return real(payload)

    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {first} {second} {third}")
    assert f"{first}: approved" in out and f"{second}: interrupted" in out, out
    assert f"{third}: not attempted" in out
    assert (home / "skills" / "int-a").is_dir() and not (home / "skills" / "int-c").exists()
    assert (_store(home) / f"{second}.applying.json").exists()
    assert {r["id"] for r in wa.list_pending(wa.SKILLS)} == {third}


@pytest.mark.platforms("posix")
def test_a_fifo_named_like_a_record_never_blocks_review(home):
    import os
    keep = _stage_skill("beside-fifo")
    fifo_id = "0badc0de" if keep != "0badc0de" else "deadbeef"
    os.mkfifo(_store(home) / f"{fifo_id}.json")
    assert [r["id"] for r in wa.list_pending(wa.SKILLS)] == [keep]
    out = _skills(f"approve {fifo_id} {keep}")
    assert f"{fifo_id}: invalid record" in out and f"{keep}: approved" in out, out


def test_a_store_without_hard_links_still_claims_once(home, monkeypatch):
    import os
    import tools.skill_manager_tool as smt
    pid = _stage_skill("no-links")
    real, calls = smt.apply_skill_pending, []

    def refuse(src, dst, *a, **k):
        raise PermissionError("hard links not permitted here")

    def applier(payload):
        calls.append(payload["name"])
        assert f"{pid}: busy" in _skills(f"approve {pid}")
        return real(payload)

    monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)  # nor an atomic no-replace rename
    monkeypatch.setattr(os, "link", refuse)
    _patch_applier(monkeypatch, applier)
    out = _skills(f"approve {pid}")
    assert f"{pid}: approved" in out and calls == ["no-links"], out
    assert not _entries(home)


def test_a_store_that_refuses_the_claim_leaves_the_record_pending(home, monkeypatch):
    import os
    pid = _stage_skill("no-moves")

    def refuse(*a, **k):
        raise PermissionError("store is read-only")

    monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)  # no atomic rename here either
    monkeypatch.setattr(os, "link", refuse)
    monkeypatch.setattr(os, "rename", refuse)
    _patch_applier(monkeypatch, lambda payload: pytest.fail("an unclaimed record must not be applied"))
    out = _skills(f"approve {pid}")
    assert f"{pid}: could not be claimed" in out and "Approved 0" in out, out
    assert _entries(home) == [f"{pid}.json"]


def test_a_failed_unlink_after_the_claim_link_leaves_one_name(home, monkeypatch):
    import os
    pid = _stage_skill("half-moved")
    real_unlink, real_rename = os.unlink, os.rename

    def refuses_source(real):
        def call(path, *a, **k):
            if str(path).endswith(f"{pid}.json") and not str(path).endswith(".applying.json"):
                raise PermissionError("sticky directory")  # the old name cannot be dropped
            return real(path, *a, **k)
        return call

    monkeypatch.setattr(wa, "_renameat_noreplace", lambda *a: False, raising=False)  # exercise the hard-link fallback
    monkeypatch.setattr(os, "unlink", refuses_source(real_unlink))
    monkeypatch.setattr(os, "rename", refuses_source(real_rename))
    _patch_applier(monkeypatch, lambda payload: pytest.fail("an unclaimed record must not be applied"))
    out = _skills(f"approve {pid}")
    assert f"{pid}: could not be claimed" in out, out
    assert _entries(home) == [f"{pid}.json"]
