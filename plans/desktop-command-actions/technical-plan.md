# Hermes Desktop QoL — implementation plan draft

**Status:** Plan only. Upstream findings are reconciled. Fable reviewed this plan as NEEDS CHANGES, with READY WITH CONDITIONS after six narrowing corrections. Those corrections are applied and recorded in review-resolution.md. Implementation and native verification are not complete.

## Upstream baseline and overlap decisions

Use verified upstream commit `4ea79443bc8e7349adb1f6516a3da3fae8225cd6` as the proposed baseline, not the inspected dirty installed checkout. Fetch the base from `NousResearch/hermes-agent` when preparing the authorized worktree; the installed checkout's `origin/main` is stale. Before starting, verify availability in the selected GitHub repository and recheck overlapping PRs. If choosing a newer base, record its SHA and reassess these interfaces before coding.

- [#147681](https://github.com/NousResearch/hermes-agent/pull/147681) and [#147708](https://github.com/NousResearch/hermes-agent/pull/147708) are merged. Reuse existing multi-gateway and terminal ownership types. Respect the explicit no-shell state. This does not make user PTY injection equivalent to the agent's configured terminal tool.
- [#147557](https://github.com/NousResearch/hermes-agent/pull/147557) is merged. Preserve skill locks throughout pending review and approval. Do not build another stock-skill protection system or change the user's live locks in this task.
- [#81403](https://github.com/NousResearch/hermes-agent/pull/81403) supplies approval-display sanitization. Reuse it without changing executable text. Do not substitute sanitized display text as the command.
- Closed, unmerged [#92017](https://github.com/NousResearch/hermes-agent/pull/92017) offers an optional renderer pattern only. Do not copy its terminal injection execution path.
- Coordinate file routing with open #132864 (Artifacts view ownership), #145995 (session-scoped directory listing), and #131544 (workspace previews). These do not cover the full transcript-card scenario inspected in the report. Recheck their current state before implementation.
- Coordinate approval storage with #142244, #119998, #131628, and #120132. Coordinate pending UI with #131600, #77038, and #144995. Reuse compatible merged fixes; do not blindly stack competing implementations.
- The bounded upstream search found no complete implementation of the requested multi-ID approval, full Desktop skill-review flow, or guarded fence execution. This is not proof that no other PR exists.
- Discord discussion was not verified. The linked GitHub changes are the verified upstream evidence.

The upstream report supersedes older statements about missing terminal ownership on current main. Earlier file and command defects remain source-inspection findings to reproduce on the pinned base, not runtime-tested results.

This contract reconciles independent architecture and usability reviews. Private session evidence is not published. Publishing this planning branch does not authorize feature implementation, real approvals, cloud launches, code pushes, merges, or deployment.

## Goal and limits

Make four everyday actions work without manual ID copying or SSH:

- Approve selected pending skills with comma- or space-separated IDs.
- Read full pending-skill diffs and use clear approval actions.
- Open Linux-owned files and folders from a Mac through the gateway.
- Put Play beside Copy on supported command fences, with the configured execution policy intact.

Keep stock file cards: icon, name, Download, and Open preview. Reuse the existing directory variant for Browse. Do not redesign these cards.

Exclude Finder mounts, directory archives, directory sync, a new remote shell, guessed SSH aliases, arbitrary language runners, and broad framework changes. Naming work is done and outside this feature.

## Before implementation

1. Incorporate the separate upstream review and identify existing fixes or overlapping work.
2. Select a clean checkout at an agreed commit SHA.
3. Record its branch, SHA, clean status, and applicable repository instructions.
4. Use a disposable worktree and isolated test profile.
5. Leave live installed files and existing dirty work untouched.

The reviewed checkout moved externally during inspection. Its Electron connection, lifecycle, cache, and main files also contained unrelated edits. Report line numbers are navigation hints, not a pinned baseline.

Prefer existing owner-routing helpers and thin adapters. Do not add a parallel connection registry, cache system, terminal system, or pending-write store.

## Shared rule: the viewer is not the owner

Three identities stay separate:

| Identity | Meaning |
|---|---|
| Originating client | The device that submitted the turn. Client OS and device labels are advisory. |
| Authoritative owner | The gateway/account, profile, session, and execution environment that own the action or file. |
| Current viewer | The client that opens the preview, downloads the file, or requests execution. |

The gateway can run tools through SSH or Docker. A gateway hostname does not identify every file owner or provide a Mac SSH address.

Bind actions to the message or artifact owner, not the focused tab or current gateway. Preserve that binding through saved history, reconnects, and gateway changes.

Resolve stable backend identity through trusted routing. A renamed connection can retain identity. A replaced URL or backend cannot silently inherit old ownership.

For old messages, use reliable stored owner and producing-cwd data. Unknown owner or cwd means unavailable or explicit resolution, never a current-gateway guess.

Keep existing origin metadata separate from authority. Do not add device fingerprinting or a broad metadata migration for this feature. Any new origin field stays advisory.

Pin asynchronous requests and results to owner, profile, session, and request generation. Discard stale view responses. Never retry an unavailable remote action locally.

## Slice A — selected skill approvals

Keep this slice separate from Desktop review UI and remote actions. Use the shared handler in `hermes_cli/write_approval_commands.py`.

### Input contract

Accepted examples:

```text
/skills approve a1b2c3d4
/skills approve a1b2c3d4 e5f6a7b8
/skills approve a1b2c3d4,e5f6a7b8
/skills approve a1b2c3d4, e5f6a7b8 0123abcd
/skills approve all
```

- Whitespace separates IDs. Spaces, tabs, and newlines are valid separators.
- Commas also separate IDs. Whitespace around commas is allowed.
- Leading, trailing, or repeated commas are errors, including `id, ,id`.
- IDs must match the generated format: eight lowercase hexadecimal characters.
- Do not repair case, strip other punctuation, accept prefixes, or accept paths.
- Deduplicate exact repeats and preserve the first occurrence's position.
- Accept case-insensitive `all` only as the sole selection.
- Reject `all` mixed with IDs before any writes.
- An empty selection or any malformed token causes zero writes and a usage error.

Validate the entire grammar before applying records. Then process valid selections sequentially in the requested order.

A valid but unknown ID gets a per-ID “not pending” result. Continue with other named IDs. Do not search another profile.

An explicit ID selects that record, not the oldest record. Standalone `all` uses the existing ordered pending snapshot. New arrivals are not added mid-request.

### Mutation and result contract

Authorize through the same path a typed `/skills approve` already uses. Do not add or relax a capability check. Record the capability actually enforced on the chosen base in the slice report.

Reuse the existing applier, validation, and scoped replay guard. The inspected store has no cross-process claim; add the narrow claim below or reuse a compatible merged fix. Never change global approval policy.

Each pending record remains its own transaction. A staged operations batch retains its internal rollback. Several selected records are not one atomic batch.

Report each ID as approved, not pending, stale/conflicting, failed, busy, or applied with cleanup failure. Report accurate totals, not a blanket success.

Keep failed records pending. Remove only successfully applied records. A changed record or conflicting target requires fresh review, not silent replacement.

Claim a validated record by atomically renaming `<id>.json` to `<id>.applying.json` in the same confined directory before applying it. A second caller whose source is gone reports busy or no longer pending; it does not apply. Never overwrite an existing claim or treat `.applying.json` as a normal pending record.

After successful application, remove the claim. If cleanup fails, retain it and report applied with cleanup failure. After a confirmed no-effect failure or successful rollback, restore the pending record without overwriting another record. If rollback or outcome is uncertain, retain the claim for reconciliation.

A leftover claim is crash evidence, not permission to retry. `/skills pending` lists it as needing reconciliation; `approve` refuses it. Test crash and cleanup boundaries. Do not build a general job database or promise exactly-once side effects. If a compatible `claim_pending` implementation from #142244 has merged, reuse it and verify these properties instead of adding another protocol.

Cancellation stops before the next record. Already completed records remain completed, with per-ID results visible.

### Narrow prerequisite and compatibility

Harden pending-store lookup before widening selection. Validate subsystem, ID, record identity, payload shape, and timestamp. Confine paths and reject redirected files.

Separate directory lookup from ID lookup. Existing empty-ID directory sentinels must not bypass ID validation. Update synthetic test IDs deliberately.

Because this handler is shared, `/memory approve/apply` also accepts the same multi-ID grammar. Cover that parity with regression tests. Do not add memory UI or multi-ID memory diff.

Keep `diff` and `reject` single-ID in this slice. Reject surplus arguments instead of ignoring them. Preserve their existing standalone forms.

Update shared usage, gateway fallback help, and slash-command documentation.

## Slice B — remote routing beneath stock cards

Split this slice into two cloud tasks. B1 fixes owner-aware file Download and Open preview. B2 adds safe classification and directory Browse after B1 passes. Reuse `sessionFileOwnerScope`, existing download transport, and `desktop-fs` routing.

For transcript actions, require a captured or reliably recovered owner. Do not use the generic download helper's foreground fallback for an unknown historical owner.

For remote-owned targets, skip Electron's local path normalizer. Send raw path text and bound session context to the owning environment.

Resolve `~` on that environment. Resolve relative paths from the producing context, not today's cwd. Never form `cwd/~/path` or substitute a same-named Mac file.

### Files and folders

Add one small owner-bound classification operation, preferably the proposed `/api/fs/stat` in the existing file router. Do not add both stat and resolve APIs.

It returns file, directory, or missing, with resolved path and limited metadata. Authorization errors remain errors, not “missing.”

Reuse owner-side resolution, SSH routing, Docker mapping, sensitive-path policy, and configured roots. Session cwd is not itself a security boundary.

Audit list alongside stat/read/download. The inspected list signature lacks session ID. Browse must preserve the same session and environment boundary as preview.

Apply consistent read policy on SSH list/read paths before exposing Browse. Enforce canonical target containment and safe file access against symlink replacement races.

The wider `write-text` policy asymmetry is separate hardening work. This read-only slice must not call or expand that route.

| Target | Existing presentation | Action |
|---|---|---|
| File | Stock Download / Open preview card | Read through its owner. Save to the clicking client. |
| Directory | Stock directory variant | Browse in the Files pane, pinned to its owner and resolved root. |
| Missing | Existing missing state | State that the path is missing on its owner, not “this computer.” |

Browse offers existing per-file preview and downloads. It does not download the directory, mount it, or open Finder for the remote source.

B2 may root the existing Files pane at the server-resolved directory for its bound connection, profile, session, and environment. Preserve that scope for descendants. Change no other pane behavior; reuse current navigation and file controls.

Keep explicit Markdown links and artifact references as the entry point. For deliverable directories, give agents concise guidance to emit links.

Do not turn every inline-code path into a card. Do not change cached prompts or old messages to add this guidance.

### Errors and compatibility

Distinguish disconnected, unknown owner, missing, access denied, unsupported backend, and canceled save. Keep sensitive server details out of error text.

Older gateways can retain supported owner-bound file actions. Disable directory Browse without safe classification and session-aware listing. Do not guess type from a trailing slash.

Downloads use current authenticated transport and the client's save dialog. Preserve overwrite consent. Show Saved only after transport completion and a returned local path.

Keep previews inert and sandboxed. Do not auto-open executable downloads. Label cached previews and temporary scratch locations truthfully.

## Slice C — readable pending-skill review

Use existing `DiffLines` / `FileDiffPanel` components. Do not reuse Git stage, revert, or ship authority for skill writes.

C1 removes the 3000-character truncation for the canonical Desktop route only and keeps messenger limits. Render recognized unified diff replies through `DiffLines`. Bind any action to the originating command and session metadata, never an ID scraped from arbitrary assistant prose.

Approve and Reject buttons on a bound diff reply submit exact `/skills approve <id>` or `/skills reject <id>` text through the same session submission path used by the composer. Require an unambiguous owning session. No new gateway RPC in C1.

C2 is a separately scoped follow-up for the structured pending list, immutable revision checks, and Approve selected. Recheck #131600 and #144995 before its handoff. Decide its request/response contract before coding; do not pretend that `skills.pending` or `skills.decide` already exists. C2 is required for the complete no-ID-copying review flow, not part of the first C1 task.

In C1, show the bound ID/profile and the returned diff, without inventing missing metadata. C2 adds the structured skill, target files, operation summary, and added/removed counts. Show stock/local provenance only when known.

Improve one-operation batch summaries through the existing gist helper. For larger batches, show bounded file summaries with access to the full operation list.

Provide a full, readable diff with scroll or virtualization. A raw staged JSON file is not a full diff view.

Fix the canonical Desktop presentation boundary. Preserve messenger output limits. Test canonical and legacy Desktop routes separately.

C1 provides single-record Approve and Reject. C2 adds Approve selected to the pending list, not a single-record view. Leave bulk Reject and multi-ID diff commands outside this plan.

C1 uses the exact typed-command path and its existing conflict checks. Do not claim that this path enforces a reviewed revision. Disable actions without a trustworthy response/session binding. C2 must bind review and action to owner, ID, and immutable pending revision; changed proposals require fresh review.

Viewing a diff never approves it. Disable stale or busy actions. Show per-ID results and retain failures for correction.

Publish outcomes through established UI/events. Do not rewrite model history or promise automatic skill reload without a verified existing mechanism.

## Slice D — guarded Play beside Copy

Split this slice into two tasks. D1 implements the renderer, eligibility, review dialog, and slash-fence submission. Shell Run in D1 always shows unavailable. D2 supplies the guarded server operation and lifecycle contract below. D2 starts with a written interface spec covering transport methods, request fields, approval-owner scope, state machine, and errors. Review that spec before implementation. D1 alone does not satisfy the user's shell execution requirement.

Add an optional Play action in the existing code-card header, beside Copy. Keep text clear of both controls.

Copy remains available everywhere. Execution requires an eligible completed assistant message in a live, writable conversation.

### Eligible commands

Eligible language tags are `sh`, `bash`, and `shell`. The configured terminal tool runs the text as it runs agent commands. The review shows its actual shell. Tags do not select or override an interpreter. `zsh` and arbitrary language runners are out of scope.

Exclude streaming messages, reasoning, previews, imported history, logs, diffs, console transcripts, unlabelled shell guesses, and arbitrary language code.

Verify that long shell fences retain Play through artifact promotion. Unsupported shell semantics produce a reason, not a rewritten command.

Treat one explicitly recognized `/skills approve ...` invocation as a separate slash action. After review, submit its exact text to the owning session through the same session submission path used by the composer. Reuse command classification. Do not add a slash RPC.

Never send slash commands to a shell. Reject mixed slash/shell fences and multiple slash invocations. Do not simulate keyboard input or ask the model to execute the command; use the deterministic slash handling on session submission.

### Review and execution contract

Play opens a review of exact text, owner, account, backend/container/SSH target, shell, and absolute cwd. Confirmation names the target.

Use the raw fence content as immutable execution text. Preserve whitespace, line endings, quotes, and heredocs. Do not reuse Copy's URL substitutions.

Eligibility is exact and does not rewrite text: reject C0/C1 controls except LF and TAB, and reject every `Default_Ignorable_Code_Point`. CR/CRLF fences are unavailable, not silently normalized. Preserve accepted content exactly.

Do not guess placeholders or strip prompts. Review shows the exact text for the user to assess. Keep display sanitization separate from executable source; reuse #81403 and never execute its escaped display string.

The server binds source identity, exact text, actor, owner, environment, cwd, shell, and request ID. Any relevant change invalidates the review.

Resolve cwd and shell from authoritative session context. Do not inherit an arbitrary human terminal's cwd or active foreground program.

Create one narrow terminal-command operation on session authority. Before calling `model_tools.handle_function_call('terminal', ...)`, enter the same approval-owner and sudo-prompt scopes that `gateway/run_turn_runner.py` and `gateway/session_sudo_prompt.py` install for a viewer-owned turn. Bind them to this operation's owning session and attached authorized viewer.

If those scopes cannot be established, return Run unavailable without execution. Do not rely on headless or unattended fallback. Preserve middleware, hooks, grants, and configured backend policy; do not add a second approval or sudo mechanism. A remote viewer can be valid: distinguish its authenticated Desktop/session authority from an unsupported external messaging source.

Require execution/control authorization and exact profile scope. Bind home, secrets, terminal policy, approval context, and environment together.

Never accept renderer overrides for force, local host, arbitrary task IDs, tool names, or middleware bypass. Never use `runInTerminal()` injection.

Clicking Run does not bypass dangerous-command approval. Preserve deny rules and configured approval behavior.

Reuse the existing masked sudo callback inside the bound owner scope. Show the actual target. Cancellation or unavailable credentials stops the operation. A user-terminal no-shell state does not by itself prove the configured agent backend has no shell; D2 must resolve its own backend capability without falling back to the viewer machine.

Never add sudo, change users, change container privileges, retry as root, or record passwords in commands, logs, chat, or new storage.

Start with bounded noninteractive commands and existing output views. Arbitrary stdin and new remote interactive shells are excluded.

### Jobs, concurrency, and failure

Reject a new Run while its conversation is active or another Run holds its execution slot. Enforce admission server-side across clients.

Return a stable operation receipt. Duplicate clicks and transport retries reuse the same request ID and return the same operation.

A deliberate later run requires a new review and request ID. Idempotent admission does not guarantee exactly-once shell side effects after a crash.

On disconnect, show unknown status until the same owner returns its receipt. Never automatically retry uncertain execution.

Resolve approvals atomically and bind them to the operation. A stale second approval cannot launch a second job.

Offer Cancel with separate requested, canceled, and already-finished states. Cancellation cannot undo completed effects. Closing the output pane does not imply cancellation.

Show running status, output, exit code, denial, timeout, cancellation, or transport failure. Preserve owner identity in results and secret-free audit evidence.

Older runtimes keep Copy and show Run unavailable. No legacy-to-local fallback and no execution on render, mount, restore, or focus.

## Acceptance and evidence

All items below are required tests, not completed results.

| Area | Acceptance criteria |
|---|---|
| Parser | Mixed separators work. Duplicate IDs apply once in order. Invalid grammar and mixed `all` cause zero writes. |
| Outcomes | Missing/stale IDs do not block valid named IDs. Replay and cleanup failures remain distinct. Totals match per-ID outcomes. |
| Approval safety | Two callers cannot replay one record. Crash uncertainty requires reconciliation. Foreign profiles and read-only actors fail. |
| Review | Full large diff is readable. Stock/local labels are grounded. Changed records invalidate actions. Messenger limits remain intact. |
| File routing | Mac viewer reads Linux data. `~` and relative paths use the owner. Same-name local files never substitute. |
| History | Old messages retain known owners. Unknown legacy owners fail closed. Replaced gateway identity requires explicit resolution. |
| Browse | Directory uses stock variant. Children retain owner/session. File download saves on viewer. No directory archive or remote Finder call. |
| File security | Denylist, roots, SSH policy, sandbox mapping, symlink races, hostile paths, and unauthorized sessions are covered. |
| Async behavior | Gateway switch, tab close, reconnect, canceled save, and stale responses cannot retarget actions. |
| Play | Copy stays intact. Streaming/non-command content cannot run. Long shell blocks retain eligibility. Slash commands never reach a shell. D1 shell execution is unavailable until D2 passes. |
| Exact text | Eligible quotes, LF/TAB, multiline content, heredocs, and whitespace match review and dispatch. Forbidden controls, CR/CRLF, and invisible Unicode fail clearly. No placeholder heuristic. |
| Execution safety | Deny hooks and middleware remain active. Backend/cwd/shell stay bound. No force, host fallback, or terminal injection. Run-launched dangerous-pattern and sudo probes reach the existing approval and masked-sudo prompts; a missing scope causes zero execution. |
| Lifecycle | Duplicate clicks, two viewers, lost acknowledgements, cancel, timeout, nonzero exit, and reconnect preserve one operation identity. |
| Sudo | Target is clear. Masked existing prompt works. Cancel/expiry fails safely. No secrets enter audit output. |

### Cloud verification

Use isolated homes, fake pending records, disposable files, and mocked backends. Do not copy personal profiles, keys, tokens, cookies, or sudo credentials.

Use the repository's PM bootstrap and `scripts/run_tests.sh`. Run relevant approval, gateway, file-routing, terminal-policy, and generated-contract tests.

Run Desktop component tests, Electron routing tests, typecheck, and lint. Extend behavior tests rather than source-text assertions.

The source reports list candidate suites. Verify paths against the pinned baseline before use. Record actual commands, outcomes, skipped tests, and environment.

Cloud tests can prove parser behavior, contracts, owner checks, rendering rules, and simulated failure handling. They cannot prove native Mac/Linux routing or sudo usability.

### Real-host acceptance

Use disposable profiles and workspaces after separate authorization. Do not run tests against the user's live pending queue.

Verify a real Mac Desktop with a Linux gateway through supported token, OAuth, and SSH connections.

Verify distinct gateway and SSH execution hosts, plus Docker mapping. Use benign identity/cwd commands to establish the actual target.

Verify native save dialogs, overwrite/cancel behavior, Downloads/Open preview, directory Browse, keyboard focus, and controls that do not obscure text.

Verify configured local, SSH, and container command backends without privilege changes. Any sudo test needs separate consent and the established masked prompt.

Verify reconnect, gateway replacement, cancellation, and missing-runtime behavior on real hosts. Test each supported shell on its actual host.

Do not mark the feature complete until these native seams pass. Mark unavailable environments as remaining work, not simulated success.

## Delivery order and review gates

1. Resolve baseline and overlap findings. No implementation before this gate.
2. Deliver Slice A with its narrow store-safety prerequisite and parser evidence.
3. Deliver Slice B routing fixes, then classification and directory Browse.
4. Deliver C1 using the existing session submission path. Scope C2 separately before its structured review UI begins.
5. Deliver D1, then D2 only after its interface, owner scope, approvals, and lifecycle contract pass review.
6. Require independent cross-family security review and real-host acceptance evidence.

Assign one cloud task at a time: A, B1, B2, C1, or D1. C2 and D2 require their own reviewed interface handoffs first. Slices remain separately reviewable. Fable's plan conditions do not replace implementation review or native acceptance.

## Bounded cloud-agent handoff prompt

> Work only on the explicitly assigned slice of this plan in a clean disposable checkout at the supplied SHA.
> First verify baseline, repository instructions, and overlap exclusions. Stop if these are missing or conflicting.
> Read your slice in technical-plan.md, its Shared rule and Acceptance sections, review-resolution.md, and the relevant topic rows in upstream.md section 3.
> technical-plan.md is canonical; its slice letters override the different labels in the upstream report. Private research reports are not required or published. The reviewed decisions needed for implementation are in this folder.
> Use isolated profiles and fake records. Do not touch live installed files, personal credentials, or real pending approvals.
> Preserve owner routing, stock cards, configured execution policy, and the exact-text contract.
> Do not use runInTerminal, add a remote shell, guess SSH aliases, redesign cards, or expand the assigned scope.
> Add focused behavior tests and run the applicable repository test commands. Report real output and remaining native checks.
> Return the branch name, head SHA, git diff --stat against the base SHA, exact test commands with captured output files, skipped tests with reasons, and remaining native checks.
> Do not merge, deploy, push, launch other cloud agents, or alter unrelated files.

This prompt is a future handoff template, not authorization to start work.
