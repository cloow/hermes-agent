# Upstream baseline and overlap map

This is a planning-time snapshot, not a live status feed. Recheck referenced PRs before implementation.

## 1. Base

Repository: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

Proposed code base: [`4ea79443bc8e7349adb1f6516a3da3fae8225cd6`](https://github.com/NousResearch/hermes-agent/commit/4ea79443bc8e7349adb1f6516a3da3fae8225cd6).

The published planning branch adds documents to this code baseline. Start from the planning branch's exact commit so the instructions are present. Do not silently rebase before a task; report any necessary base change.

## 2. Already merged at planning time

- [#147681](https://github.com/NousResearch/hermes-agent/pull/147681): persistent multi-gateway connections.
- [#147708](https://github.com/NousResearch/hermes-agent/pull/147708): terminal-tab gateway ownership and explicit no-shell behavior.
- [#147557](https://github.com/NousResearch/hermes-agent/pull/147557): skill locks that block agent edits.
- [#81403](https://github.com/NousResearch/hermes-agent/pull/81403): safer approval display for hidden Unicode/control bytes.
- [#147802](https://github.com/NousResearch/hermes-agent/pull/147802): continued Desktop access to legacy client-labelled sessions.

Reuse these features. Do not create duplicate connection managers or skill-lock systems.

## 3. Topic-specific overlap checks

### A. Pending approval and review

These were open at the research snapshot:

- [#142244](https://github.com/NousResearch/hermes-agent/pull/142244), [#119998](https://github.com/NousResearch/hermes-agent/pull/119998), [#131628](https://github.com/NousResearch/hermes-agent/pull/131628), and [#120132](https://github.com/NousResearch/hermes-agent/pull/120132): competing pending-store hardening changes.
- [#131600](https://github.com/NousResearch/hermes-agent/pull/131600): structured pending-memory review and decision work.
- [#77038](https://github.com/NousResearch/hermes-agent/pull/77038): pending-list ordering/grouping.
- [#144995](https://github.com/NousResearch/hermes-agent/pull/144995): JSON pending output.

The inspected baseline still accepts only the first explicit approval ID. Preserve explicit selection order and existing standalone `all` semantics. Do not blindly stack competing store patches.

### B. Remote file cards

- [#132864](https://github.com/NousResearch/hermes-agent/pull/132864): Artifacts-view ownership; not the entire transcript-card path.
- [#145995](https://github.com/NousResearch/hermes-agent/pull/145995): session-scoped directory listing and cache keys.
- [#131544](https://github.com/NousResearch/hermes-agent/pull/131544): workspace preview handling.

Coordinate those seams before B1/B2. Keep the existing cards and pin actions to the originating session's owner.

### C. Command-fence Run

Closed and unmerged [#92017](https://github.com/NousResearch/hermes-agent/pull/92017) offers a renderer pattern, not a suitable backend execution path.

Do not reuse its user-PTY injection for configured agent execution. D2 must establish the existing viewer-owned approval/sudo scopes before calling the terminal tool.

## 4. Limits

The bounded search found no complete implementation of this plan. That does not prove no overlapping PR exists.

The recalled Discord announcement was not verified. The GitHub links are the cited upstream evidence.

`technical-plan.md` defines the canonical task labels and contracts. Security findings discovered during implementation follow `SECURITY.md`; do not publish new in-scope vulnerabilities in planning or task reports.
