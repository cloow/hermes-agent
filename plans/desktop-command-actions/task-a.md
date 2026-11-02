# Task A — batch approval of selected pending skills

Paste this prompt into an ordinary Claude Code cloud session after selecting `cloow/hermes-agent` and branch `docs/desktop-command-actions-plan`:

```text
Implement Task A only: batch approval of selected pending skill writes.

Start by verifying the selected repository is cloow/hermes-agent. Record the initial branch and full commit SHA. The starting commit must contain plans/desktop-command-actions/technical-plan.md and descend from upstream baseline 4ea79443bc8e7349adb1f6516a3da3fae8225cd6. Work only on the session's assigned implementation branch, not main or the published planning branch. Stop if repository, branch safety, or ancestry is unclear.

Read root AGENTS.md and the relevant hermes_cli, tools, and tests instructions. Read technical-plan.md sections Shared rule, Slice A, Acceptance, and Cloud verification; review-resolution.md; and upstream.md section 3A. Do not implement the other slices or read private conversation logs.

Recheck overlapping upstream PRs before changing the pending store. If you cannot access GitHub, report that blocker rather than assuming the overlap check passed. Reuse compatible fixes already on this base. Do not merge or cherry-pick competing open PRs automatically.

Implement these behaviors:
- /skills approve accepts one or more exact eight-character lowercase hexadecimal IDs separated by whitespace or commas.
- Validate the entire input before any writes. Reject malformed tokens, empty comma items, and all mixed with IDs.
- Deduplicate exact repeats in the requested order. Report a truthful result for every selected ID.
- Unknown IDs do not cause other valid IDs to disappear. Failed or conflicting records remain reviewable.
- Keep all as a separate existing selection. Do not silently widen a selection.
- The shared /memory approve/apply parser gets the same grammar and regression coverage. Do not add memory UI.
- Keep reject and diff single-ID; reject surplus arguments instead of ignoring them.
- Preserve the existing authorization path, profile scope, skill locks, validation, and replay guards.
- Add only the narrow per-record claim and crash/cleanup handling specified in Slice A, unless a compatible implementation already exists.
- Never approve real pending writes or change global approval policy.

Use a disposable HERMES_HOME and fake records. Bootstrap with the committed PM workflow in CONTRIBUTING.md. No personal tokens, SSH keys, real skill queues, or live app state belong in this VM. If you discover a new in-scope security vulnerability, follow SECURITY.md's private-reporting rule; do not publish exploit details.

Prove the relevant failures on the base with focused behavior tests, then make them pass. Run the canonical scripts/run_tests.sh, the affected regression suites, and applicable repository checks. Verify current test filenames instead of copying stale paths. tests/tools/test_write_approval.py is a known baseline suite; create focused new parser/claim tests as needed. No npm or Electron work is required for this task.

Do not add the Run button, remote file routing, skill review UI, a new RPC, a new model tool, a general transaction database, or unrelated cleanup. Stop if the task needs a broader design than the narrow contract.

Commit the implementation locally in the assigned cloud branch. Do not push, open a PR, merge, deploy, install into a live app, or launch other agents. Do not rewrite the planning documents to make failing behavior appear compliant.

Return the initial SHA, final branch and SHA, diff --stat against the initial SHA, exact test commands, captured test-output file paths, failures or skipped checks with reasons, and any remaining native checks. Distinguish tests actually run from recommendations. End after Task A for coordinator review.
```

## Acceptance checklist

- Comma-separated, whitespace-separated, and mixed selections work.
- Malformed input and mixed `all` cause zero writes.
- Duplicate IDs apply once, in first-occurrence order.
- Results and totals match each requested record's actual outcome.
- Competing callers cannot replay one claimed record.
- Confirmed failures restore pending state; uncertain outcomes require reconciliation.
- Shared memory parsing, single-ID verbs, locked skills, and profile isolation remain correct.
- Real records and application state are untouched.
