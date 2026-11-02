# Fresh Hermes session handoff

You are the local coordinator, not the cloud implementation worker.

## Context

The user requested core Desktop quality-of-life improvements: command-fence Play, multi-ID skill approval, readable skill-review actions, and owner-correct remote file cards.

Independent reviews and an Astra synthesis produced the technical plan. Fable required six narrowing corrections; those are applied in this branch.

The feature is not implemented. Task A is the first bounded implementation assignment. C2 and D2 still need reviewed interfaces before coding.

## Start procedure

1. Read this folder's README and task-a.md.
2. Verify this checkout is on `docs/desktop-command-actions-plan` and has no unexpected changes.
3. Verify the fork's published branch SHA matches the local planning commit.
4. Preserve the pinned upstream code baseline and all existing worktrees. Do not update the installed app.
5. Load the Claude Code operating skill and check current official cloud-session documentation. Follow cli-launch.md; CLI only, no Chrome automation.
6. Check `claude --version`, `claude --help`, and `claude auth status`. Require subscription authentication for the account holding the cloud credits, not Console/API billing. Stop for secure CLI sign-in when missing.
7. If local planning commits differ from the published SHA, stop for approval to publish the documentation. Never launch the old plan silently, push without approval, or treat local-only changes as uploaded.
8. Create the independent fork-only clone specified in cli-launch.md. Verify its sole remote, branch, clean status, baseline ancestry, and SHA against the published planning branch. Preserve existing worktrees/remotes.
9. Start exactly one ordinary cloud session using cli-launch.md's guarded `--ref docs/desktop-command-actions-plan --forward-home-settings=false --cloud` command and the literal prompt extracted from task-a.md. Run setup and dispatch in the same tracked shell. Do not use local print-mode implementation, Remote Control, Projects, Routines, or additional workers.
10. Capture the returned session URL. A successful detached creation may print its URL and exit 0: do not relaunch it. If account-enabled CLI attachment is available, read back the same session to verify repository/base and accepted Task A prompt. If attachment is account-gated, report confirmed creation but unverified worker/provisioning state and ask the user to inspect that exact URL manually. Print-mode follow-up messages are not status probes. Stop on uncertain dispatch status; do not launch a replacement. Report launch evidence separately from implementation/review status.

The user pasting the launch prompt authorizes one Task A cloud session. It does not authorize subsequent tasks, code publication, PR creation, merging, or deployment.

## Important environment facts

The Studio folder has a PM-built `.venv`, root npm dependencies, and the Electron binary prepared. The unchanged code's write-approval suite passed 24 tests.

The shared worktree remotes name the upstream repository `origin` and the user's fork `fork`. Do not rename or rewrite these shared remotes. A separate clone with one fork remote makes CLI targeting unambiguous.

Claude Code 2.1.316 is installed on Linux via `npm install -g @anthropic-ai/claude-code` in the existing user prefix. Version/help checks passed. CLI authentication reported `loggedIn: false`; secure subscription login remains a prerequisite. No cloud session has been launched. Recheck these facts in the new session.

The user's main Chrome on the MacBook is signed in to Claude and showed access to the fork. That is not Linux CLI authentication. Browser automation was stopped at the user's request after repeated debugging permission prompts. Do not reopen that route or copy browser credentials.

Never request passwords, tokens, or login codes in chat. Use `claude auth login` through its supported secure user flow when needed; do not use `--console` or API-key billing as a substitute. Do not install additional tooling to evade authentication.

The requested funding source is existing cloud credit. Check current balance, expiry, and ordinary-session eligibility before dispatch; do not assume the old screenshot is current or that `--cloud` guarantees promotional billing. If the CLI cannot expose this information, ask for user confirmation from their usage page without automating Chrome. Do not enable paid overage, buy credits, or switch billing sources. Projects and Routines remain excluded by the user's request.

## Review loop

Keep the implementation task separate from local acceptance. Review its actual diff and captured tests. If corrections are needed, send them to the same cloud task.

Do not claim the Run button or the full quality-of-life feature is done when Task A passes. Remote routing, review UI, and guarded shell execution remain later tasks.

Do not approve live skill or memory changes while testing. Do not copy user credentials, session databases, or private reports into the cloud worker.
