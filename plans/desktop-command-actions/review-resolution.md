# Review resolution

## Plan gate

Independent architecture and usability reviewers supplied findings. Astra compiled the implementation draft. Fable (`claude-fable-5-1`, runtime-reported) reviewed the resulting plan and spot-checked source at the pinned baseline.

Fable's original verdict was **NEEDS CHANGES**, becoming **READY WITH CONDITIONS** after six specified narrowing edits. Those edits were applied by the coordinator. No second Fable review or implementation test pass is claimed.

| Required correction | Applied decision |
|---|---|
| Terminal dispatch alone does not attach viewer prompts | D2 must enter existing approval-owner and masked-sudo scopes, or execute nothing. Explicit prompt-path tests are required. |
| The proposed slash/approval services do not exist | C1 and D1 use the existing session submission path. C2 receives a separate structured interface plan. |
| Control bytes and placeholders were ambiguous | Permit LF/TAB, reject other C0/C1 and Default_Ignorable characters. No placeholder guessing or silent CRLF normalization. |
| Concurrent approvals lacked a specified mechanism | Narrow same-directory claim and reconciliation contract, or reuse a compatible merged implementation. |
| Run was too large for one cloud task | D1 is UI plus slash commands. D2 begins with a separately reviewed backend interface. |
| Worker handoff required too much stale research | Read the assigned contract, this resolution, and relevant upstream rows. Return branch/SHA and actual test evidence. |

## Remaining conditions

- Give each cloud worker one bounded task: A, B1, B2, C1, or D1.
- C2 and D2 require their own reviewed interface handoffs before implementation.
- Record the actual base SHA and recheck relevant upstream overlaps before each task.
- D1 and D2 require independent cross-family security review before merge.
- Cloud evidence does not replace native acceptance for Mac/Linux routing, save dialogs, shell behavior, or masked sudo.
- D1's unavailable shell button is an intermediate state, not delivery of working shell execution.

## Clarifications

A human terminal's no-shell transport does not establish whether the agent's configured backend has a shell. Resolve the actual backend and viewer approval authority without falling back locally.

Restore a failed pending claim only after confirmed no-effect failure or successful rollback. An uncertain outcome remains claimed for reconciliation.

The shared approval parser also gives `/memory approve/apply` multi-ID grammar; no memory UI is added.

Older research statements about missing gateway terminal ownership were superseded by merged upstream work. Historical user conversations and private reports are not published or required.

## Evidence limits

The plan gate used source inspection, not runtime tests. A separate setup smoke test later passed the unchanged baseline write-approval suite. Neither result proves the requested feature works.
