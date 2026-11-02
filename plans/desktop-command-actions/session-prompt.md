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
5. Load the Claude Code operating skill and check current official cloud-session documentation.
6. Verify the Claude account and its access to `cloow/hermes-agent` before launching anything.
7. Start one ordinary cloud session on this fork and planning branch, using the prompt in task-a.md.
8. Report the session URL and selected repository/branch. Stop if authentication or repository access is unavailable.

The user pasting the launch prompt authorizes one Task A cloud session. It does not authorize subsequent tasks, code publication, PR creation, merging, or deployment.

## Important environment facts

The Studio folder has a PM-built `.venv`, root npm dependencies, and the Electron binary prepared. The unchanged code's write-approval suite passed 24 tests.

The shared worktree remotes name the upstream repository `origin` and the user's fork `fork`. A bare cloud CLI launch can choose the wrong repository. Prefer the web repository and branch selectors unless the CLI's actual target is verified.

During setup, the accessible local browser reached Claude's sign-in screen. No Claude login was available in the browser vault. The Claude CLI was not installed. GitHub CLI authentication worked, but it could not list GitHub App installations with its token.

Therefore Claude account authorization is **not verified**. Do not infer it from the successful Git push. The user's already signed-in browser can use claude.ai/code directly.

Do not install extra tooling solely to work around a sign-in requirement. Never request passwords or login codes in chat. Use supported secure sign-in tools or ask the user to sign in.

Use ordinary cloud sessions to consume the promotional credit. Claude Projects and Routines are excluded from that promotion. Check the current balance and expiry before dispatch; do not assume the old screenshot is still current.

## Review loop

Keep the implementation task separate from local acceptance. Review its actual diff and captured tests. If corrections are needed, send them to the same cloud task.

Do not claim the Run button or the full quality-of-life feature is done when Task A passes. Remote routing, review UI, and guarded shell execution remain later tasks.

Do not approve live skill or memory changes while testing. Do not copy user credentials, session databases, or private reports into the cloud worker.
