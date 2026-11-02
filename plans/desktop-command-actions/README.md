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
Read plans/desktop-command-actions/README.md, session-prompt.md, and cli-launch.md. Continue the CLI-only handoff for Task A. Verify Claude CLI subscription authentication, cloud-credit eligibility, and the published planning SHA before dispatch. If the revised plan is not published, stop for approval to push these documentation commits. Launch exactly one ordinary Claude Code cloud session from a separate clone of cloow/hermes-agent on docs/desktop-command-actions-plan. Do not implement locally, automate Chrome, use Projects/Routines, or start other tasks. Preserve all review gates and report the verified cloud session URL. Stop on missing authentication or ambiguous launch status; never blindly retry.
```

The detailed instructions are in [session-prompt.md](session-prompt.md).

## CLI-only launch

Follow [cli-launch.md](cli-launch.md). Claude Code 2.1.316 is installed on the Linux coordinator in the existing npm global prefix. `claude --version` and `claude --help` passed; `--cloud` is available. `claude auth status` reported **loggedIn: false**. Main Chrome's Claude login does not authenticate this CLI.

Do not run a bare cloud launch from this linked worktree: its shared `origin` points upstream. The runbook uses a fresh, independent clone whose only remote is the fork, and checks branch and SHA before launch. Do not change shared remotes.

This preparation pass launches nothing. The revised handoff must be reviewed and published with approval before the next session dispatches Task A. No browser automation or repeated Chrome debugging prompts.

## Documents

| File | Purpose |
|---|---|
| [plan.md](plan.md) | Plain-English user experience and scope |
| [technical-plan.md](technical-plan.md) | Canonical contracts and acceptance criteria |
| [task-a.md](task-a.md) | First bounded cloud implementation prompt |
| [session-prompt.md](session-prompt.md) | Local Hermes orchestration handoff |
| [cli-launch.md](cli-launch.md) | CLI authentication, fork isolation, and one-session dispatch |
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

The original planning commit is published to the fork. Revised local CLI-handoff commits are not published until separately approved. No upstream PR or feature PR is opened.
The preparation session does not start a cloud run. The next session checks publication and authentication before starting the authorized Task A run.

The implementation worker can edit, test, and commit in its assigned cloud branch.
It must not merge, deploy, push code, open a PR, change live profiles, or launch additional workers without a separate instruction.
A later coordinator reviews the results and obtains approval before publishing code.
