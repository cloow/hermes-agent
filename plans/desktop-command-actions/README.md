# Desktop command actions — start here

## Ready state

- Repository: [cloow/hermes-agent](https://github.com/cloow/hermes-agent).
- Planning branch: `docs/desktop-command-actions-plan`.
- Upstream code baseline: `4ea79443bc8e7349adb1f6516a3da3fae8225cd6`.
- This branch adds planning documents only. No feature code is implemented.
- Fable reviewed the plan. Its required narrowing corrections are applied; implementation conditions remain.

The first cloud task is **A: batch skill approval**. Do not start the full roadmap in one session.

## Start a fresh Hermes session

Select the Studio folder labelled **hermes: Desktop command actions** and start a new chat in that folder.

Paste this:

```text
Read plans/desktop-command-actions/README.md and session-prompt.md in that folder. Continue this handoff: verify the published planning branch, then prepare and launch only Task A as an ordinary Claude Code cloud session using my existing cloud credits. Do not implement the task locally or use Claude Projects/Routines. Preserve the plan's review gates, report the cloud session URL, and stop for sign-in if my Claude account is unavailable.
```

The detailed instructions are in [session-prompt.md](session-prompt.md).

## Start directly in Claude Code on the web

1. Open [claude.ai/code](https://claude.ai/code) with the account that holds the cloud credit.
2. Select **cloow/hermes-agent**, not the upstream repository.
3. Select **docs/desktop-command-actions-plan**.
4. Start an ordinary cloud session, not a Claude Project or Routine.
5. Paste the prompt from [task-a.md](task-a.md).

The worktree's shared Git remote `origin` points upstream. Do not assume a bare `claude --cloud` command selects this fork.
Use the web repository and branch selectors unless the CLI's effective target is independently verified.

GitHub access and Claude authorization are separate. Publishing a branch does not connect the Claude GitHub App.
If this fork is missing from the repository selector, grant the Claude GitHub App access to this repository through Claude's onboarding.

## Documents

| File | Purpose |
|---|---|
| [plan.md](plan.md) | Plain-English user experience and scope |
| [technical-plan.md](technical-plan.md) | Canonical contracts and acceptance criteria |
| [task-a.md](task-a.md) | First bounded cloud implementation prompt |
| [session-prompt.md](session-prompt.md) | Local Hermes orchestration handoff |
| [review-resolution.md](review-resolution.md) | Fable findings and corrections |
| [upstream.md](upstream.md) | Public upstream references and overlap checks |

Private chat transcripts, user pending records, credentials, and local audit inventories are deliberately excluded.

## Setup verification

The local worktree was prepared with the repository's PM-built Python test environment and root npm dependencies.
The Electron binary installation and root-install assertion completed successfully. No app or gateway was launched.

Baseline smoke command:

```bash
HERMES_PYTHON="$PWD/.venv/bin/python" scripts/run_tests.sh -j 2 tests/tools/test_write_approval.py
```

Observed result on the unchanged upstream code: **24 passed, 0 failed**.
This proves the baseline test environment, not the requested feature.

`npm ci` succeeded but reported 38 dependency advisories: 34 moderate and 4 high.
These are baseline advisories; no dependency upgrades or audit fixes were performed in this documentation task.

A cloud worker starts in a fresh VM. Bootstrap there using `CONTRIBUTING.md`; the local `.venv` and `node_modules` are not uploaded.

## Permissions

The planning branch is published to the fork. No upstream PR or feature PR is opened.
The setup session does not start a cloud run. Pasting the handoff prompt starts the next task.

The implementation worker can edit, test, and commit in its assigned cloud branch.
It must not merge, deploy, push code, open a PR, change live profiles, or launch additional workers without a separate instruction.
A later coordinator reviews the results and obtains approval before publishing code.
