# Task A — CLI cloud launch runbook

## Stop boundary

This is a runbook for the **next** coordinator session, not permission to dispatch during handoff preparation. Install and review now; launch only after the user resumes with the README prompt. No feature implementation on the coordinator. Do not use browser automation, Projects, Routines, Remote Control, `--teleport`, or local `claude -p` implementation.

## Verified preparation facts

- Original published planning SHA: `b655b7f533b3cd248ce2e8f3b97725184f1c537a`; it matched the clean local planning branch before this CLI documentation revision.
- Linux install: `npm install -g @anthropic-ai/claude-code`, using the existing npm prefix. `claude --version` returned `2.1.316 (Claude Code)`; help advertises `--cloud [description|session_id|url]`.
- `claude auth status` returned `loggedIn: false`, `authMethod: none`. No login or cloud launch was attempted during CLI preparation. Browser login is separate.
- Revised documentation must be committed, reviewed, and published with approval before launch. Compare current SHAs; do not pin the launch to the original SHA above.

Official references checked during preparation:

- https://code.claude.com/docs/en/claude-code-on-the-web
- https://code.claude.com/docs/en/cli-reference

The documented basic command is `claude --cloud "task description"`, but it can fall back to uploading a local bundle when GitHub App preflight fails. This runbook requires `--ref docs/desktop-command-actions-plan --forward-home-settings=false` before `--cloud "$prompt"`: in installed version 2.1.316, explicit ref refuses the no-GitHub-source fallback, and disabling home-settings forwarding avoids copying personal Claude configuration. These flags exist in the installed CLI even though default help omits them. Revalidate their support on version changes; stop rather than omit either guard. Do not use `--on-branch`, which would target the planning branch for implementation.

## 1. Authentication and funding gate

Run `claude --version`, `claude --help`, and `claude auth status` without starting an agent. Require the user's subscription account holding the cloud credits. If unauthenticated, use the supported `claude auth login` user flow, then recheck status. Never request login codes in chat, copy browser credentials, use `--console`, or substitute API billing. Do not automate Chrome; user-operated OAuth consent is separate from browser automation.

Confirm cloud-credit balance, expiry, and ordinary-session eligibility. If CLI status does not show these, ask the user to confirm them from their usage page. Subscription authentication alone does not prove promotional billing. Do not buy credit or enable paid overage.

GitHub CLI access does not prove the Claude account's GitHub connection. The Mac browser previously displayed `cloow/hermes-agent`, but recheck access in the launch flow. Keep the explicit `--ref` guard: missing or transient GitHub App preflight must fail closed, not silently upload a local bundle. Stop for supported onboarding if required. Do not upload personal GitHub tokens through `/web-setup` without separate approval.

## 2. Publication and fork isolation gate

From the planning worktree, verify clean status and branch, record `git rev-parse HEAD`, and compare it to:

```bash
git ls-remote https://github.com/cloow/hermes-agent.git refs/heads/docs/desktop-command-actions-plan
```

Require a clean worktree with the reviewed changes committed. Verify `git diff --name-only 4ea79443bc8e7349adb1f6516a3da3fae8225cd6..HEAD` contains only `plans/desktop-command-actions/` paths. If the remote differs, stop for approval to push **documentation only**. Verify `git remote get-url --push fork` is `https://github.com/cloow/hermes-agent.git`; the only approved publication command is `git push fork refs/heads/docs/desktop-command-actions-plan:refs/heads/docs/desktop-command-actions-plan`. Never use a bare push or push to upstream `origin`. After an approved push, read back the exact remote ref and require equality. Do not change the baseline or any shared remote.

Use a new ordinary clone, not another linked worktree. Run the following only after the gates above pass, in Bash. **Start one tracked interactive PTY or tmux shell in the planning worktree, and run all remaining setup, extraction, and dispatch blocks in that same shell.** Do not spawn a new shell for dispatch or assume it inherits shell variables/cwd. If the shell is lost before dispatch, stop and repeat preflight in an explicitly selected clone; never send the multiline prompt via tmux keystrokes. The clone has its own Git configuration and only the fork as `origin`:

```bash
set -euo pipefail
planning_root="$PWD"
expected_sha="$(git rev-parse HEAD)"
test "$(git branch --show-current)" = docs/desktop-command-actions-plan
test -z "$(git status --porcelain)"
remote_line="$(git ls-remote https://github.com/cloow/hermes-agent.git refs/heads/docs/desktop-command-actions-plan)"
test "$expected_sha" = "${remote_line%%[[:space:]]*}"
: "${TMPDIR:?Use the coordinator scratch directory}"
launch_dir="$(mktemp -d "$TMPDIR/desktop-task-a-cli.XXXXXX")"
git clone --single-branch --branch docs/desktop-command-actions-plan \
  https://github.com/cloow/hermes-agent.git "$launch_dir/repo"
cd "$launch_dir/repo"
test "$(git remote)" = origin
test "$(git remote get-url origin)" = https://github.com/cloow/hermes-agent.git
test "$(git remote get-url --push origin)" = https://github.com/cloow/hermes-agent.git
test "$(git branch --show-current)" = docs/desktop-command-actions-plan
test "$(git rev-parse HEAD)" = "$expected_sha"
test -z "$(git status --porcelain)"
git merge-base --is-ancestor 4ea79443bc8e7349adb1f6516a3da3fae8225cd6 HEAD
test -f plans/desktop-command-actions/technical-plan.md
test -f plans/desktop-command-actions/cli-launch.md
git remote -v
git rev-parse HEAD
```

Record the clone path and SHA in the coordinator's handoff. Do not set local-bundle overrides, install project dependencies, or run a local implementation agent. Recheck the remote planning SHA immediately before dispatch; stop if it moved.

## 3. Extract literally, then dispatch once

In the same tracked shell, from that verified clone, extract only the single `text` fence. Keep shell interpolation out of the prompt itself. Do not open another PTY/tmux shell between these blocks:

```bash
prompt="$(python - <<'PY'
from pathlib import Path
text = Path('plans/desktop-command-actions/task-a.md').read_text()
assert text.count('```text\n') == 1
prompt, remainder = text.split('```text\n', 1)[1].split('\n```', 1)
assert prompt.startswith('Implement Task A only:')
assert 'Do not push, open a PR, merge, deploy' in prompt
print(prompt)
PY
)"
```

After confirming the preflight evidence, recheck targeting and issue **once in that same tracked shell**, retaining its output and process/session handle. Guards precede `--cloud` so the prompt binds to that option:

```bash
cd "$launch_dir/repo"
test "$(git remote)" = origin
test "$(git remote get-url origin)" = https://github.com/cloow/hermes-agent.git
test "$(git branch --show-current)" = docs/desktop-command-actions-plan
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$expected_sha"
remote_line="$(git ls-remote https://github.com/cloow/hermes-agent.git refs/heads/docs/desktop-command-actions-plan)"
test "$expected_sha" = "${remote_line%%[[:space:]]*}"
test -n "$prompt"
claude --ref docs/desktop-command-actions-plan --forward-home-settings=false --cloud "$prompt"
```

Do not substitute `claude -p "$prompt"`, `--remote-control`, `--teleport`, or a bare local Claude session. Do not assume print-mode output flags for sending to an existing cloud session also apply to creating one. Preserve the terminal output even when creation exits immediately.

## 4. Verify the same session; never duplicate dispatch

Creation has two valid outcomes in 2.1.316:

- **Detached:** CLI prints `Created cloud session: ...`, a `View:` URL/session ID, and may suggest `claude --teleport`, then exits 0. This confirms creation, not provisioning or worker acceptance. Do not treat it as a failed connection or retry creation. Do not teleport.
- **Attached (account-gated):** CLI stays attached; read its initial state. Confirm worker acceptance of Task A, repository/base SHA, assigned non-planning implementation branch, and successful provisioning.

For a captured session ID/URL, `claude --cloud <session-id-or-url>` may attach, but if it reports `Attaching to an existing cloud session is not enabled for your account.`, stop there. Report confirmed creation and the exact URL, with provisioning/worker state **not verified**, and ask the user to inspect that exact session manually. Do not automate Chrome. `claude -p "..." --cloud <session-id>` sends a follow-up message; it is not readback and must not be used as a status probe. Never claim implementation or tests passed merely because creation succeeded.

If dispatch times out or output is ambiguous, retain the process/log and **stop**. A cloud session may already exist: do not rerun creation. If CLI attachment cannot read the state, report the URL as unverified and ask the user to inspect that exact session; do not revert to Chrome automation.

Report the session URL, repository, starting branch/SHA, assigned implementation branch when available, and actual provisioning status. No URL exists until a real launch returns one.

## 5. Preserve acceptance and publication gates

The Task A fenced prompt is unchanged: exact ID grammar, full-input validation before writes, ordered deduplication, truthful per-record results, narrow claims/crash handling, shared memory parsing, locks/profile/replay protection, disposable test records, baseline-red tests and captured canonical test evidence. Other slices remain out of scope.

The worker may commit in its cloud branch but must not push, open a PR, merge, deploy, alter live profiles, or start other agents. Local acceptance reviews the actual diff and test evidence; corrections go to the same task. `--teleport` requires a published branch and cannot be used under the no-push gate; obtain evidence from the session or seek separate publication approval. If the service cannot retain results without publication, stop for approval rather than silently relaxing no-push. C2/D2 interface review and later independent review gates remain unchanged.
