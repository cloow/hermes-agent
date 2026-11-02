#!/usr/bin/env python3
"""Shared handlers for the /memory and /skills write-approval subcommands."""

from __future__ import annotations

import json
from typing import List, Optional

from tools import write_approval as wa


def _fmt_state(subsystem: str) -> str:
    on = wa.write_approval_enabled(subsystem)
    return f"{subsystem}.write_approval = {'on' if on else 'off'}"


def _fmt_pending_list(subsystem: str) -> str:
    records = wa.list_pending(subsystem)
    attention = _fmt_unapprovable(subsystem)
    if not records:
        return "\n".join([f"No pending {subsystem} writes.", *attention])
    lines = [f"Pending {subsystem} writes ({len(records)}):"]
    for r in records:
        origin = r.get("origin", "foreground")
        tag = " [auto]" if origin == "background_review" else ""
        lines.append(f"  {r['id']}{tag}  {r.get('summary', '')}")
        if subsystem == wa.MEMORY:
            lines.extend(f"      {line}" for line in _matched_entries(r["payload"]))
    lines.extend(attention)
    lines.append("")
    lines.append(f"Apply: /{subsystem} approve <id> [<id> ...]   Reject: /{subsystem} reject <id>")
    if subsystem == wa.SKILLS:
        lines.append("Review full diff: /skills diff <id>")
    return "\n".join(lines)


def _fmt_unapprovable(subsystem: str) -> list[str]:
    """Store entries approve refuses, so a person can see and settle them."""
    entries = wa.list_unapprovable(subsystem)
    if not entries:
        return []
    store = wa._pending_dir(subsystem)
    lines = ["", f"Needs attention ({len(entries)}, not approvable):"]
    for pid, kind in entries:
        if kind == "claimed":
            lines.append(f"  {pid}  approval interrupted or unfinished — needs reconciliation: check whether it "
                         f"took effect, then remove {store / (pid + '.applying.json')}")
        else:
            lines.append(f"  {pid}  unreadable or invalid record — inspect {store / (pid + '.json')} "
                         f"or /{subsystem} reject {pid}")
    return lines


def handle_pending_subcommand(
    subsystem: str, args: list[str], *, memory_store=None, set_mode_fn=None) -> Optional[str]:
    """Dispatch a /memory or /skills write-approval subcommand.

    ``memory_store`` applies approved memory writes (CLI passes its live store; gateway a freshly
    loaded one); ``set_mode_fn`` persists the write_approval boolean. Returns text for the user,
    or None when the args are not a write-approval subcommand so the caller falls through to its
    other handling (e.g. /skills search).
    """
    try:
        return _dispatch(subsystem, args, memory_store, set_mode_fn)
    except wa.PendingStoreError as e:
        return f"Refusing to use the {subsystem} pending store: {e}"


def _dispatch(subsystem: str, args: list[str], memory_store, set_mode_fn) -> Optional[str]:
    if not args:
        return f"{_fmt_state(subsystem)}\n\n" + _fmt_pending_list(subsystem)
    sub, rest = args[0].lower(), args[1:]
    if sub == "pending":
        return _fmt_pending_list(subsystem)
    if sub in {"approve", "apply"}:
        return _approve(subsystem, rest, memory_store)
    if sub in {"reject", "deny", "drop"}:
        return _reject(subsystem, rest)
    if sub == "diff" and subsystem == wa.SKILLS:
        return _diff(rest)
    if sub in {"approval", "mode"}:  # 'mode' kept as a back-compat alias
        return _set_approval(subsystem, rest, set_mode_fn)
    return None  # not ours — caller handles


def _usage(subsystem: str, verb: str = "approve|reject") -> str:
    return f"Usage: /{subsystem} {verb} <id>  (or 'all')"


def _approve_usage(subsystem: str) -> str:
    return (f"Usage: /{subsystem} approve <id> [<id> ...]  (ids separated by spaces or commas), "
            f"or /{subsystem} approve all")


def parse_selection(args: list[str]) -> str | list[str]:
    """``"all"`` or the selected ids in first-occurrence order. Whitespace and commas separate
    ids; every id must be exactly as minted (8 lowercase hex), with no repair. Raises ValueError
    for an empty selection, an empty comma item, a malformed id, or ``all`` with anything else."""
    text = " ".join(args)
    if not text.strip():
        raise ValueError("no ids given")
    tokens: list[str] = []
    for item in text.split(","):
        words = item.split()
        if not words:
            raise ValueError("empty item between commas")
        tokens.extend(words)
    if any(t.lower() == "all" for t in tokens):
        if len(tokens) != 1:
            raise ValueError("'all' must be the only selection")
        return "all"
    for t in tokens:
        if not wa.is_pending_id(t):
            raise ValueError(f"{t[:40]!r} is not a pending id (8 lowercase hex characters)")
    return list(dict.fromkeys(tokens))


# outcome -> (label in the totals line, counts as applied)
_OUTCOMES = {
    "approved": ("approved", True), "cleanup_failed": ("applied with cleanup failure", True),
    "missing": ("not pending", False), "busy": ("busy", False), "invalid": ("invalid", False),
    "store_error": ("store error", False), "changed": ("changed", False), "failed": ("failed", False), "conflict": ("conflicting", False), "uncertain": ("uncertain", False),
    "interrupted": ("interrupted", False), "skipped": ("not attempted", False)}


def _approve(subsystem: str, rest: list[str], memory_store) -> str:
    try:
        selection = parse_selection(rest)
    except ValueError as e:
        return f"{_approve_usage(subsystem)}\n{e}. Nothing was applied."
    # What is approved is what the store held when the command started: every selected record is
    # read now and a claim later must find exactly these bytes. Later arrivals wait for the next run.
    if selection == "all":
        start = {r["id"]: (wa.PENDING, r) for r in wa.list_pending(subsystem)}
        if not start:
            return f"No pending {subsystem} writes."
    else:
        start = {pid: wa.peek_pending(subsystem, pid) for pid in selection}
    outcomes = _run_selection(subsystem, start, memory_store)
    return _fmt_approve_result(subsystem, outcomes)


def _run_selection(subsystem: str, start: dict, memory_store) -> list[tuple[str, str, str, dict]]:
    """``(id, outcome, line, applier result)`` per selected id, in order. An interrupt anywhere stops
    before the next record; what finished keeps its result and the rest are reported not attempted."""
    outcomes: list[tuple[str, str, str, dict]] = []
    current = None
    try:
        for pid, (state, rec) in start.items():
            current = pid
            outcome, line, result, stop = _approve_one(subsystem, pid, memory_store, state, rec)
            outcomes.append((pid, outcome, line, result))
            current = None
            if stop:
                break
    except KeyboardInterrupt:
        if current is not None:
            outcomes.append((current, "interrupted", f"{current}: interrupted — see /{subsystem} pending: it is "
                                                     f"still pending or claimed for reconciliation", {}))
    except wa.PendingStoreError as e:  # the store as a whole (locked too long, redirected): stop here
        if current is not None:
            outcomes.append((current, "store_error", f"{current}: not applied — {e}", {}))
    done = {pid for pid, *_ in outcomes}
    outcomes.extend((pid, "skipped", f"{pid}: not attempted (stopped)", {}) for pid in start if pid not in done)
    return outcomes


def _fmt_approve_result(subsystem: str, outcomes: list[tuple[str, str, str, dict]]) -> str:
    applied = [(pid, result) for pid, o, _, result in outcomes if _OUTCOMES[o][1]]
    out = [f"Approved {len(applied)} {subsystem} write(s)."]
    sections = (
        # A memory 'replace' overwrites the WHOLE matched entry (#117952); the approver
        # is the last person who can notice a clause went missing, so show what was lost.
        ("replaced", "Overwrote entire entry (re-add anything you still need):"),
        # A patch keeps the rest of the entry, so show it as it was, not as lost text.
        ("patched", "Patched entry (as it was before the edit):"),
        ("removed", "Removed entry (re-add anything you still need):"))
    for kind, title in sections:
        lines = [f"  {pid}: {text}" for pid, result in applied for text in _changed_entries(result, kind)]
        if lines:
            out.append(title)
            out.extend(lines)
    counts = {label: sum(1 for _, o, *_ in outcomes if o == key) for key, (label, _) in _OUTCOMES.items()}
    out.append(f"{len(outcomes)} selected: " + ", ".join(f"{n} {label}" for label, n in counts.items() if n))
    out.extend(f"  {line}" for _, _, line, _ in outcomes)
    return "\n".join(out)


def _refusal(subsystem: str, pid: str, state: str) -> tuple[str, str]:
    return {
        wa.MISSING: ("missing", f"{pid}: not pending"),
        wa.BUSY: ("busy", f"{pid}: busy — being applied elsewhere or interrupted earlier; see /{subsystem} pending"),
        wa.INVALID: ("invalid", f"{pid}: invalid record, not applied — inspect it or /{subsystem} reject {pid}"),
        wa.CHANGED: ("changed", f"{pid}: changed since it was checked; not applied, left pending for fresh "
                                f"review (/{subsystem} pending)"),
        wa.STORE_ERROR: ("store_error", f"{pid}: could not be claimed (pending store error); left pending"),
    }[state]


def _approve_one(subsystem: str, pid: str, memory_store, state: str, reviewed
                 ) -> tuple[str, str, dict, bool]:
    """Claim, apply and settle one record: ``(outcome, line, applier result, stop)``. Each record is its
    own transaction; only a confirmed no-effect failure puts it back in the queue. ``state``/``reviewed``
    are what the store held when the command started; a record must still be exactly that."""
    if state == wa.PENDING:
        state, rec = wa.claim_pending(subsystem, pid, reviewed)
    if state != wa.CLAIMED:
        return (*_refusal(subsystem, pid, state), {}, False)
    try:
        ok, err, result, certain = _apply_one(subsystem, rec, memory_store)
    except KeyboardInterrupt:
        return "interrupted", f"{pid}: interrupted; claim kept for reconciliation", {}, True
    if ok:
        try:
            released = wa.release_claim(subsystem, pid)
        except KeyboardInterrupt:  # it was applied: report it so, then stop
            return ("cleanup_failed", f"{pid}: applied; interrupted before its claim file was removed — kept for "
                                      f"reconciliation, never re-applied", result, True)
        if released:
            return "approved", f"{pid}: approved", result, False
        return ("cleanup_failed", f"{pid}: applied, but its claim file could not be removed; kept for "
                                  f"reconciliation and never re-applied", result, False)
    if not certain:
        return "uncertain", f"{pid}: outcome uncertain ({err}); claim kept for reconciliation", {}, False
    try:
        restored = wa.restore_claim(subsystem, pid)
    except KeyboardInterrupt:
        return ("failed", f"{pid}: failed ({err}); interrupted while putting it back — see /{subsystem} pending",
                {}, True)
    if restored:
        return "failed", f"{pid}: failed ({err}); left pending", {}, False
    return "conflict", (f"{pid}: failed ({err}); claim kept — it could not go back in the queue "
                        f"(its id is taken again or the store refused), reconcile by hand"), {}, False


def _changed_entries(result: dict, kind: str) -> list[str]:
    """Full text of every entry a memory write changed, single-op or batch shape."""
    single = result.get(f"{kind}_entry")
    if kind == "patched" and single is None:
        single = result.get("patched_entry_before")
    batch = result.get(f"{kind}_entries") or {}
    return ([single] if single else []) + [batch[k] for k in sorted(batch, key=int)]


def _matched_entries(payload) -> list[str]:
    """The full entry each staged memory replace/remove is pinned to: the summary shows only
    the old_text search string, and approval applies to this entry, not to that search."""
    from tools.memory_tool import destructive_ops
    return [f"{op['action']}s entry: {op['matched_entry']}" if op.get("matched_entry")
            else f"{op['action']}: unpinned legacy target \u2014 reject and recreate before approving"
            for op in destructive_ops(payload)]


def _apply_one(subsystem: str, rec, memory_store):
    """``(ok, error, result, certain)`` — *result* is the applier's full payload. Applied only on an
    explicit ``success: True``. A failure is confirmed to have left nothing behind only when the applier
    says so explicitly (``success: False`` with an error, after its own rollback); an exception, a
    malformed or missing outcome, or a failed rollback did not settle that (``certain`` False)."""
    payload = rec.get("payload", {})
    try:
        if subsystem == wa.MEMORY:
            if memory_store is None:
                return False, "memory store unavailable", {}, True
            from tools.memory_tool import apply_memory_pending
            result = apply_memory_pending(payload, memory_store)
        else:
            from tools.skill_manager_tool import apply_skill_pending
            result = json.loads(apply_skill_pending(payload))
    except Exception as e:
        return False, str(e), {}, False
    if not isinstance(result, dict):
        return False, "unreadable applier result", {}, False
    if result.get("success") is True:
        return True, "", result, True
    error = result.get("error")
    if result.get("success") is False and isinstance(error, str) and error and not result.get("rollback_failed"):
        return False, error, result, True
    return False, (error if isinstance(error, str) and error else "no clear outcome from the applier"), {}, False


def _single_target(subsystem: str, verb: str, rest: list[str], *, allow_all: bool):
    """The one id (or ``all``) a single-record verb names, else the reply explaining why not."""
    if len(rest) != 1 or "," in rest[0]:
        return None, (_usage(subsystem, verb) if allow_all else f"Usage: /{subsystem} {verb} <id>")
    target = rest[0]
    if allow_all and target.lower() == "all":
        return "all", None
    if not wa.is_pending_id(target):
        return None, (f"{target[:40]!r} is not a pending id (8 lowercase hex characters, "
                      f"as /{subsystem} pending shows them).")
    return target, None


def _reject(subsystem: str, rest: list[str]) -> str:
    target, err = _single_target(subsystem, "reject", rest, allow_all=True)
    if err:
        return err
    if target != "all":
        return {
            wa.DISCARDED: f"Rejected pending {subsystem} write '{target}'.",
            wa.MISSING: f"No pending {subsystem} write with id '{target}'.",
            wa.BUSY: (f"Pending {subsystem} write '{target}' is being applied or awaits reconciliation "
                      f"(see /{subsystem} pending); not rejected."),
            wa.STORE_ERROR: f"Could not reject pending {subsystem} write '{target}': the pending store refused it.",
        }[wa.discard_pending(subsystem, target)]
    states = [(rec["id"], wa.discard_pending(subsystem, rec["id"])) for rec in wa.list_pending(subsystem)]
    out = [f"Rejected {sum(1 for _, st in states if st == wa.DISCARDED)} pending {subsystem} write(s)."]
    out += [f"  {pid}: not rejected ({'claimed' if st == wa.BUSY else 'store error'})"
            for pid, st in states if st in (wa.BUSY, wa.STORE_ERROR)]
    return "\n".join(out)


def _diff(rest: list[str]) -> str:
    target, err = _single_target(wa.SKILLS, "diff", rest, allow_all=False)
    if err:
        return err
    rec = wa.get_pending(wa.SKILLS, target)
    if not rec:
        return f"No pending skill write with id '{target}'."
    return f"# Pending skill write {rec['id']}: {rec.get('summary', '')}\n\n" + wa.skill_pending_diff(rec)


_APPROVAL_VALUES = {
    **dict.fromkeys(("on", "true", "yes", "1", "enable", "enabled"), True),
    **dict.fromkeys(("off", "false", "no", "0", "disable", "disabled"), False)}


def _set_approval(subsystem: str, rest: list[str], set_mode_fn) -> str:
    """Turn the approval gate on/off for a subsystem."""
    if not rest:
        return (f"{_fmt_state(subsystem)}\n"
                f"Set with: /{subsystem} approval <on|off>")
    arg = rest[0].strip().lower()
    enabled = _APPROVAL_VALUES.get(arg)
    if enabled is None:
        return f"Invalid value '{arg}'. Use: on or off."
    if set_mode_fn is None:
        val = "true" if enabled else "false"
        return (f"To change the {subsystem} approval gate, run:\n"
                f"  hermes config set {subsystem}.write_approval {val}")
    try:
        set_mode_fn(enabled)
    except Exception as e:
        return f"Failed to set {subsystem}.write_approval: {e}"
    return f"{subsystem}.write_approval set to '{'on' if enabled else 'off'}'."
