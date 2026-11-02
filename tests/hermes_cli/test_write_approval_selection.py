"""Selection grammar for ``/skills approve`` and ``/memory approve|apply`` (shared handler).

One or more exact pending ids (eight lowercase hex characters, as ``stage_write`` mints them),
separated by whitespace and/or commas; ``all`` only on its own. The whole selection is validated
before any record is touched, every selected id gets its own truthful result, and ``reject`` /
``diff`` stay single-id. Driven through ``handle_pending_subcommand`` against a temp HERMES_HOME
with fake staged records, applied by the real skill and memory appliers.
"""

from __future__ import annotations

import pytest

from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools import write_approval as wa

_SKILL = "---\nname: {name}\ndescription: selection test {name}\n---\n\n# {name}\n\nBody.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    h.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def _stage_skill(name: str) -> str:
    rec = wa.stage_write(wa.SKILLS, {"action": "create", "name": name, "content": _SKILL.format(name=name)},
                         summary=f"create {name}", origin="foreground")
    return rec["id"]


def _skill_exists(home, name: str) -> bool:
    return (home / "skills" / name / "SKILL.md").is_file()


def _pending_ids(subsystem: str) -> set[str]:
    return {r["id"] for r in wa.list_pending(subsystem)}


def _skills(args: str) -> str:
    return handle_pending_subcommand(wa.SKILLS, args.split())


def _unused_id(*taken: str) -> str:
    for candidate in ("0badc0de", "deadbeef", "12345678"):
        if candidate not in taken:
            return candidate
    raise AssertionError("no unused id")


@pytest.mark.parametrize("sep", [" ", ",", ", ", " ,", "\t", "\n", " , "])
def test_two_ids_with_any_separator_apply_both(home, sep):
    a, b = _stage_skill("sel-a"), _stage_skill("sel-b")
    out = _skills(f"approve {a}{sep}{b}")
    assert _skill_exists(home, "sel-a") and _skill_exists(home, "sel-b"), out
    assert not _pending_ids(wa.SKILLS), out
    assert "Approved 2 skills write(s)." in out
    assert f"{a}: approved" in out and f"{b}: approved" in out


def test_mixed_separators_select_exactly_the_named_records(home):
    a, b, c, untouched = (_stage_skill(n) for n in ("mix-a", "mix-b", "mix-c", "mix-d"))
    out = handle_pending_subcommand(wa.SKILLS, ["approve", f"{a},", b, f"{c}"])
    assert all(_skill_exists(home, n) for n in ("mix-a", "mix-b", "mix-c")), out
    assert not _skill_exists(home, "mix-d"), "an explicit selection must never widen"
    assert _pending_ids(wa.SKILLS) == {untouched}


def test_explicit_id_selects_that_record_not_the_oldest(home):
    older, newer = _stage_skill("old-one"), _stage_skill("new-one")
    _skills(f"approve {newer}")
    assert _skill_exists(home, "new-one") and not _skill_exists(home, "old-one")
    assert _pending_ids(wa.SKILLS) == {older}


def test_duplicates_apply_once_in_first_occurrence_order(home, monkeypatch):
    import tools.skill_manager_tool as smt
    a, b = _stage_skill("dup-a"), _stage_skill("dup-b")
    real, order = smt.apply_skill_pending, []

    def recording(payload):
        order.append(payload["name"])
        return real(payload)

    monkeypatch.setattr(smt, "apply_skill_pending", recording)
    out = _skills(f"approve {b} {a},{b} {a}")
    assert order == ["dup-b", "dup-a"], out
    assert out.count(f"{b}: approved") == 1 and out.count(f"{a}: approved") == 1, out
    assert out.index(f"{b}: approved") < out.index(f"{a}: approved")


def test_unknown_id_does_not_hide_or_block_valid_ids(home):
    a, b = _stage_skill("known-a"), _stage_skill("known-b")
    missing = _unused_id(a, b)
    out = _skills(f"approve {a} {missing} {b}")
    assert _skill_exists(home, "known-a") and _skill_exists(home, "known-b"), out
    assert f"{missing}: not pending" in out
    assert "Approved 2 skills write(s)." in out
    assert "3 selected: 2 approved, 1 not pending" in out


def test_failed_record_stays_pending_and_the_rest_still_apply(home):
    first = _stage_skill("ok-first")
    bad = wa.stage_write(wa.SKILLS, {"action": "patch", "name": "no-such-skill", "old_string": "x",
                                     "new_string": "y"}, summary="patch missing", origin="foreground")["id"]
    last = _stage_skill("ok-last")
    out = _skills(f"approve {first},{bad},{last}")
    assert _skill_exists(home, "ok-first") and _skill_exists(home, "ok-last"), out
    assert _pending_ids(wa.SKILLS) == {bad}, "a failed record must stay reviewable"
    assert f"{bad}: failed" in out
    assert "3 selected: 2 approved, 1 failed" in out


@pytest.mark.parametrize("tail", [
    "{a},,{b}", "{a}, ,{b}", ",{a}", "{a},", "{a} , , {b}",          # empty comma items
    "{a} {b}x", "{a} ABCDEF12", "{a} abc", "{a} 0123456789", "{a} ../../auth",  # malformed ids
    "{a} /tmp/x", "{a} {b};", "{a} g1234567", "{a} {b}.json", "{a} a1b2c3d",
    "all {a}", "{a},all", "{a} ALL", "all all", "all,",                # all mixed with anything
])
def test_invalid_selection_writes_nothing(home, tail):
    a, b = _stage_skill("inv-a"), _stage_skill("inv-b")
    out = _skills("approve " + tail.format(a=a, b=b))
    assert out.startswith("Usage: /skills approve"), out
    assert not _skill_exists(home, "inv-a") and not _skill_exists(home, "inv-b"), out
    assert _pending_ids(wa.SKILLS) == {a, b}


def test_empty_selection_is_a_usage_error(home):
    a = _stage_skill("empty-sel")
    for args in (["approve"], ["approve", ","], ["approve", " "]):
        out = handle_pending_subcommand(wa.SKILLS, args)
        assert out.startswith("Usage: /skills approve"), (args, out)
    assert _pending_ids(wa.SKILLS) == {a}


@pytest.mark.parametrize("spelling", ["all", "ALL", "All"])
def test_all_alone_still_approves_the_whole_snapshot(home, spelling):
    _stage_skill("all-a"), _stage_skill("all-b")
    out = _skills(f"approve {spelling}")
    assert _skill_exists(home, "all-a") and _skill_exists(home, "all-b"), out
    assert "Approved 2 skills write(s)." in out


def test_reject_and_diff_stay_single_id(home):
    a, b = _stage_skill("one-a"), _stage_skill("one-b")
    for args in (f"reject {a} {b}", f"reject {a},{b}", f"diff {a} {b}", f"reject all {a}", f"reject {a} all"):
        out = _skills(args)
        assert out.startswith("Usage: /skills"), (args, out)
    assert _pending_ids(wa.SKILLS) == {a, b}, "surplus arguments must not reject anything"
    assert "selection test one-a" in _skills(f"diff {a}")
    assert f"Rejected pending skills write '{a}'" in _skills(f"reject {a}")
    assert "Rejected 1 pending skills write(s)." in _skills("reject all")


def test_reject_and_diff_refuse_malformed_ids(home):
    a = _stage_skill("shape-a")
    for args in ("reject ../../auth", "reject A1B2C3D4", "diff /etc/passwd", "diff abc"):
        out = _skills(args)
        assert "not a pending id" in out, (args, out)
    assert _pending_ids(wa.SKILLS) == {a}


# ── /memory shares the parser ────────────────────────────────────────────────

def _stage_memory(text: str) -> str:
    return wa.stage_write(wa.MEMORY, {"action": "add", "target": "user", "content": text},
                          summary=text, origin="foreground")["id"]


@pytest.mark.parametrize("verb", ["approve", "apply"])
def test_memory_approve_takes_the_same_multi_id_grammar(home, verb):
    from tools.memory_tool import MemoryStore
    store = MemoryStore()
    store.load_from_disk()
    a, b, c = _stage_memory("mem-a"), _stage_memory("mem-b"), _stage_memory("mem-c")
    out = handle_pending_subcommand(wa.MEMORY, [verb, f"{c},", a], memory_store=store)
    assert "Approved 2 memory write(s)." in out, out
    assert store.user_entries == ["mem-c", "mem-a"], "applied once each, in the requested order"
    assert _pending_ids(wa.MEMORY) == {b}


@pytest.mark.parametrize("args", ["{a},,{b}", "all {a}", "{a} nope"])
def test_memory_invalid_selection_writes_nothing(home, args):
    from tools.memory_tool import MemoryStore
    store = MemoryStore()
    store.load_from_disk()
    a, b = _stage_memory("keep-a"), _stage_memory("keep-b")
    out = handle_pending_subcommand(wa.MEMORY, ["approve", *args.format(a=a, b=b).split()], memory_store=store)
    assert out.startswith("Usage: /memory approve"), out
    assert store.user_entries == [] and _pending_ids(wa.MEMORY) == {a, b}


def test_memory_reject_refuses_surplus_arguments(home):
    a, b = _stage_memory("rej-a"), _stage_memory("rej-b")
    out = handle_pending_subcommand(wa.MEMORY, ["reject", a, b])
    assert out.startswith("Usage: /memory"), out
    assert _pending_ids(wa.MEMORY) == {a, b}


def test_another_profiles_record_is_not_pending_here(home, tmp_path, monkeypatch):
    theirs = _stage_skill("foreign-skill")
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    out = _skills(f"approve {theirs}")
    assert f"{theirs}: not pending" in out and "Approved 0" in out, out
    monkeypatch.setenv("HERMES_HOME", str(home))
    assert _pending_ids(wa.SKILLS) == {theirs} and not _skill_exists(home, "foreign-skill")
