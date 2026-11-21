# Pi command timeout investigation and robustness candidate

> **Historical evidence (2026-11-20).** Later context, runtime and project work
> superseded parts of this RPC diagnostic. Current contracts: [runtime abstraction](runtime-abstraction.md).
> See [documentation status](documentation-status.md).


Follow-up: the [November 20 runtime audit](2026-11-20-runtime-audit.md) inspected the
retained live-demo sessions and identified context exhaustion and pre-prompt compaction
as the next issue. It records the subsequent tested fix and recovery steps. The initial
investigation below did not inspect those sessions.

The subsequent [Resume context maintenance](resume-context.md) adds recovery before
unpausing and bounded incremental room context. The timeout patch below is historical;
it did not by itself repair an already oversized conversation.

Human request: investigate the frontend department's `Pi command timed out` and
improve backend robustness (2026-11-20). This is separate from the deferred watchdog.

## Diagnosis and limits of evidence

The message originates in `RpcProcess.command`, whose default acknowledgement
budget is 10 seconds. It is **not** RoomService's 300-second total run deadline.
During ordinary delivery startup it could identify `get_state` or `prompt`; the old
message omitted the command and phase. Bridge initialization timeout has a different
message. Stop-path command errors are caught during cleanup. No live database,
sessions, provider calls or native transcripts were inspected, so this work does not
claim to establish the exact command or root cause of the reported incident.

Source inspection and synthetic subprocess tests reproduced two independent defects:

1. The command timer began only after `send`, so write-lock contention and stdin
   backpressure were unbounded by the command deadline.
2. The event consumer began only after prompt acknowledgement. A Pi input handler
   that requested an unsupported dialog before acknowledging could wait for the host
   while the host waited for its acknowledgement, producing a timeout.

Pi's installed RPC references specify asynchronous events, subscription before
prompting, and dialog responses that can block command handling. Tests reproduce
those protocol cases without launching a real Pi agent or a model.

## Candidate changes

- Start the existing command deadline before writing, covering lock, drain and
  response in one budget. No default deadline value is increased or removed.
- Use allowlisted command/phase diagnostics; never include arguments, raw command
  names outside the allowlist, rejected native payloads, stderr or credentials.
- Explicitly mark a missing prompt acknowledgement as **acceptance unknown**, not
  successful completion or permission to replay. No prompt retry is introduced.
- Start collecting events before sending prompt; apply the existing unsupported
  dialog cancellation response at that point too. Final output is still returned
  only after a valid acknowledgement and `agent_settled`; a completed event without
  an acknowledgement does not invent acceptance.
- Cancel/join the event collector on every exit and clean pending futures even when
  write failures and response-reader failures race.

Unchanged: bridge readiness/model/session verification, permissions, owner/runtime
credentials, five-minute supervisor, clear-queue-before-abort, signal escalation,
confirmed-stop requirements and restart/Pause non-replay. Existing edits are not
rolled back. This patch is isolated from the task feature and is not a watchdog.

## Verification and integration status

Initial six regression cases: five failed against the old implementation, one passed.
Expanded suite covers nine new cases including input lock/backpressure, waiter
cancellation, safe diagnostic phase, pre-ack dialog, completion before ack, missing
state acknowledgement/no prompt, and missing prompt acknowledgement with/without
completion events. Full ordinary suite: **191 passed, 12 browser tests deselected**;
Ruff lint and format checks passed. Synthetic processes only, temporary data, uv-only.

Candidate remains on `fix/backend-rpc-robustness`; not deployed or applied to a live
process. Review and explicit integration evidence are still required. Do not claim
that current frontend execution has been repaired merely because source tests pass.
