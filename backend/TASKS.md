# Ongoing tasks and explicit human decisions — v1 contract

Approved by the human on 2026-11-20. Implementation lives in `tasks.py`, `task_api.py`
and the existing Store/RoomService integration. No runtime tools, authentication,
permission, deadline or cancellation policy changes are part of this feature.

## Identity, provenance and lifecycle

- Each newly addressed ordinary human room message creates one root per resolved
  recipient, even if paused or admission is refused by the existing queue rules.
  Unaddressed notes create none. Multi-recipient roots share the original **one**
  message/chain/delivery allowance. No historical backfill or inferred tasks.
- Only the human creates children. Creation is metadata only; owner, parent, root and
  original source are immutable. Parent edges are decomposition, not dependencies.
- Routing uses stable owner IDs. Renames update display; old public message labels
  remain immutable. Deleted/disabled owners remain historical but cannot receive work.
- Task lifecycle is human-controlled `open|closed`, separate from delivery outcome.
  Closing rejects linked queued/running/stopping deliveries (including peer work),
  never stops execution or closes children. Parent closure does not close children.
- `task_deliveries` links each exact delivery and an immutable context snapshot;
  `task_messages` records causal public outputs. Shared chain IDs do not mix sibling
  histories. Peer requests inherit the initiating delivery's task and context, not
  the peer's sibling root. Handoffs never create children.
- Prompts include the queued task snapshot outside the recent-50-message window.
  Public details omit native session references, credentials and raw runtime output.

## Owner-only HTTP API

All routes use the unchanged `/api/` owner credential and origin boundary. Runtime
credentials may only use the existing bridge-message route, not these APIs. Bodies
are strict: unknown fields/type coercions are rejected. 422 errors omit raw inputs;
404 means not found; 409 is `{detail,code}` for task conflicts.

- `GET /api/tasks?cursor=0&limit=100` → `{tasks,next_cursor,open_count}`.
  All lifecycles; UI filters ongoing while retaining ancestors. Cursor is opaque
  monotonic row position. Limit 1–200. No task collection is added to `/api/state`.
- Summary: `id,parent_id,root_id,title,context,owner_lead_id,revision,lifecycle`,
  `source_message_id,source_chain_id,created_at,updated_at`, current historical-safe
  `owner:{id,name,handle,enabled,deleted_at,revision,status}`, `child_count`,
  `delivery_summary` counts, `latest_delivery`, and
  `instruction_action:{mode:execute|record_note|blocked,reason}`.
- `GET /api/tasks/{id}?cursor=0&limit=50` → `{task,messages,deliveries,instructions,
  next_cursor,deliveries_truncated,action_requests,action_requests_truncated}`.
  Message cursor is sequence; messages ascending, 1–200/page. Related deliveries
  capped at 200/page with explicit truncation; instruction entries include text and
  current `delivery_state`. Decision history is newest 200 (including blocked and
  resolved), with explicit truncation. Each response uses one read snapshot.
- `POST /api/tasks` (201): `{parent_id,parent_revision,owner_lead_id,title,context,
  idempotency_key}` → child summary. Title 1–120; context up to 8000 characters.
- `PATCH /api/tasks/{id}`: `{task_revision,title?,context?,lifecycle?}` → current
  summary. Increments revision; empty patches rejected. Does not dispatch.
- `POST /api/tasks/{id}/instructions` (201): `{text,task_revision,idempotency_key,
  mode:execute|record_note}` → `{id,task_id,message_id,chain_id,delivery_id,
  disposition,reason,created_at}`. Text 1–32000; request key 1–128 characters.

### Instruction admission

`execute` writes a public human message and a new normally bounded human chain,
then queues one delivery to the immutable owner. Mentions are literal for routing;
there is no fan-out. Existing FIFO/per-owner serialization applies; no steering,
priority bypass or claim that the agent has read/applied the instruction.

`record_note` writes public history and a chain with **no delivery**, even if the
room resumes concurrently. It never auto-executes. Execute racing Pause/stopping
returns 409, not a silently converted note. Closed/unavailable targets reject both
modes. Advisory summary capability never replaces transactional revalidation.

Idempotency fingerprints and receipts persist in the same writer transaction as
all records. Exact retry returns the original receipt **before** stale-revision/
availability checks; changed content under that operation's key returns 409.
Retries cannot revive canceled deliveries or mint roots/budgets. Receipts report
original admission; task detail reports the delivery's current outcome.

Conflict codes: `stale_task`, `task_closed`, `owner_unavailable`, `room_paused`,
`owner_stopping`, `task_busy`, `idempotency_conflict`, `stale_action`.

## Actionable-only Activity / single choice

No run outcome (`completed`, `failed`, etc.) automatically creates a human decision.
The only Activity records are explicit unresolved, currently actionable requests.

- `POST /api/tasks/{id}/action-requests` (201): `{question,options:[{id,label}],
  source_message_id?,task_revision,idempotency_key}`. Question 1–2000; 2–8 distinct
  option IDs (1–64), labels 1–300. Optional source must belong to this exact task.
- `GET /api/action-requests?cursor=0&limit=100` → `{action_requests,next_cursor}`.
  Each includes `id,task_id,question,options,status,revision,source_message_id`,
  timestamps, resolution and current task summary. Limit 1–200.
- `POST /api/action-requests/{id}/resolve`: `{option_id,revision,task_revision,
  idempotency_key,mode}` → `{action_request_id,status:resolved,option_id,revision,
  instruction}`. Validates exactly one offered option and atomically stores its
  resolution plus a public task instruction using the admission rules above.
  Conflicts/invalid choices leave the request unresolved and write no instruction.
- Closed tasks or deleted/disabled owners make unresolved decisions nonactionable;
  they are omitted from Activity but retained in task detail, not auto-resolved.
  Reopen/re-enable restores unresolved items; deletion never changes ownership.
- **Authoring limitation:** v1 creates requests through the owner API. There is no
  model-text detector, newly privileged runtime tool or authoring form promised.
  The frontend offers real radio choices for persisted requests; empty Activity is
  valid when no request exists. Resolution is a human choice, not execution approval
  beyond existing department permissions.

## Storage, verification and release boundary

Additive transactional schema v2: `tasks`, `task_deliveries`, `task_messages`,
`task_instructions`, `task_requests`, `action_requests`. v0→v1→v2 and v1→v2 retain
prior rows, tombstones, sessions and receipts. Failures roll back the whole upgrade;
unknown future versions are refused before schema/journal writes.

Store/API/service tests use temporary SQLite and synthetic runtimes: shared budgets,
exact sibling/peer provenance, strict owner boundary, immutable snapshots, FIFO,
record-note/Pause/restart non-replay, retained deletion history, atomic resolution,
rollback and controlled two-connection delete/Pause/close/retry/resolution races.
See final integration evidence for combined frontend/browser/package results.

Before human relaunch: stop all writers, back up the entire actual persistent data
and native sessions, use the same absolute `--data-dir`, and do not downgrade after
migration. The current CLI opens Store before binding, so a failed port bind may
already migrate data. No live data access, migration, restart or model calls were
performed as part of development. The proposed progress watchdog is deferred in
[`docs/watchdog-follow-up.md`](../docs/watchdog-follow-up.md); current deadline and
stop behavior remain unchanged.
