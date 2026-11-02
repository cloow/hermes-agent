# Hermes: run commands and review changes without copy-paste

**Status: Fable-reviewed plan, with the requested corrections applied. Ready for bounded tasks under the conditions below. No implementation or cloud session has started.**

## What changes for you

### 1. Run a command where you read it

Supported command blocks get a **▶ Run** button beside **Copy**. The controls do not cover the text.

Run shows the exact command, target machine, account, shell, and working folder before execution. The command uses the session's configured backend. If its approval or sudo prompt cannot be attached safely, Run stays unavailable.

Existing approval rules still apply. Existing secure sudo prompts still apply. The button never adds sudo or silently runs on another machine.

The block shows progress, output, and the exit result. Double-clicking does not start two jobs. An unavailable target shows an error.

Slash commands use the existing session submission path, not a shell. The first supported action is `/skills approve ...`.

The first UI task enables slash commands only. Shell Run remains unavailable until the separate backend task passes its tests.

### 2. Approve several selected skills

Both forms work:

```text
/skills approve a1b2c3d4, e5f6a7b8
/skills approve a1b2c3d4 e5f6a7b8
```

The IDs here are examples, not real approvals.

Each ID gets its own result. Repeated IDs run once. Invalid syntax causes no writes. Unknown or stale IDs do not become silent successes.

`all` remains a separate choice. Combining `all` with specific IDs is an error.

### 3. Read the change before approving it

The pending-skill view shows the skill, files, summary, and full readable diff together.

It provides **Approve**, **Reject**, and **Approve selected** controls. You do not need to copy IDs for the normal review flow.

The first review task makes single-record diffs readable and adds Approve/Reject controls. The structured pending list and Approve selected follow separately.

That later task binds approval to the reviewed proposal version. Failed proposals remain visible. Existing skill locks remain in force.

### 4. Open remote files from the same chat

Keep the stock **Download / Open preview** card.

A Linux file opens through its owning gateway even when you view the chat on a Mac. Downloads save on your viewing device.

A directory opens in the in-app Files pane through **Browse**. No manual SSH, Finder mount, or directory archive is required.

Old messages must not follow whichever gateway is selected now. Missing files and unknown owners produce clear errors.

Agents provide explicit file or directory links. This version does not convert every inline path into a button.

## What we reuse

Upstream already merged multi-gateway connections, per-gateway terminal tabs, skill locks, and safer approval displays.

Reuse these features. Do not build another connection manager, terminal system, or skill-lock system.

The proposed base is upstream commit `4ea79443bc8e7349adb1f6516a3da3fae8225cd6`. Recheck overlapping PRs before work starts.

Leave the installed app, existing feature branches, and unrelated local edits untouched.

## How we split the work

This is now several small changes, not one small button patch.

1. **Batch approval:** parser, per-ID results, and a small per-record claim to prevent concurrent replay.
2. **Remote files:** one task for card routing, then another for directory Browse.
3. **Skill review:** readable single-record diffs and controls first. The structured list and Approve selected need a separate interface plan.
4. **Command Run:** one task for the button and slash commands. Shell execution needs a separate, reviewed backend interface before coding.

Use one cloud task per assigned change. Do not give one worker the entire backlog. Review each change before dependent work starts.

The command Run change needs the strongest security review. Do not connect it to the existing terminal-text injection shortcut.

## What proves it works

Cloud tests cover command parsing, ownership checks, diff rendering, approval rules, duplicate requests, errors, and cancellation.

Real-host tests cover Mac-to-Linux routing, native save dialogs, the configured local/SSH/container backends, and secure sudo prompts.

Use disposable profiles and files. Never use your real pending approvals or copy personal credentials into a cloud worker.

A screenshot or a worker's success summary is not enough. Each result needs the tested commit, command output, and remaining limits.

## Cloud handoff gate

Before a cloud task starts, provide its repository, reachable base SHA, assigned change, plan files, and test requirements.

The technical contract is in `technical-plan.md`. Upstream evidence is in `upstream.md`.

Fable reviewed the plan and required six corrections. Those corrections are now applied. Its result is conditional, not approval of unbuilt code.

Each worker gets one task. The structured review interface and shell execution interface need review before their implementation starts.

Publishing the plan or branches, starting cloud work, merging, and deployment remain separate actions.

Do not merge or deploy as part of an implementation task.
