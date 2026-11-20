# Context maintenance on Resume — November 20, 2026

Resume now prepares the conversations of every enabled department before the room
accepts new work. This addresses the live-demo loop in which repeated full room
snapshots accumulated in Pi until even conversation compaction failed.

## User behavior

1. Pause the room and wait for confirmed stops. Click **Resume room**.
2. The room shows **Preparing room**, with progress on each department card.
   Preparation keeps healthy context, compacts large conversations, and switches
   to fresh context when the old conversation cannot be recovered.
3. Wait for **Room running**, then send a new addressed request. Notes sent during
   preparation remain public notes and are not queued for later execution.

**Cancel resume** stops preparation. An unconfirmed stop keeps the affected
department unavailable and prevents another Resume. A failed runtime/model check
leaves the room paused with a department context note. Correct its settings and
Resume again. Disabled departments are checked on a later Resume after enabling
them; preparation never activates a disabled department.

Compaction can use the department's selected provider/model. It runs without work
tools, the room bridge, or delivery credentials. Preparation does not send an agent
prompt, restart an old task, or change a department's model, workspace or permission.

## Context policy

Pi's `get_state` must confirm the requested model, conversation and idle state.
`get_session_stats.contextUsage` supplies the current context estimate; lifetime
token totals are not used. Immediately after native compaction, Pi may report null
usage, so the adapter estimates the active `get_messages` projection using UTF-8
size. Estimates are approximate, not provider-exact tokenizer measurements.

- At or below 60% of the selected context window: retain the conversation, with
  no model call. Empty conversations also require no compaction.
- Above 60% but below 90%: attempt one native `compact` call using the selected
  model. Its instructions preserve goals, decisions, file paths, completed work,
  unresolved issues and approval limits, while omitting repeated snapshots, stale
  requests and raw logs. The result must reduce context below the target.
- At or above 90%, or if compaction fails, times out, or does not free enough
  space: request a fresh conversation after confirming process exit. This avoids
  submitting an already oversized history to another doomed summary call.
- An active conversation whose size cannot be estimated is retained on disk and
  replaced for future input. Invalid runtime/model/session selection instead fails
  preparation; it is not treated as successful recovery.

The core allocates the new conversation ID transactionally, retains the prior
session reference, and increments the configuration revision. Public messages,
department identity, historical sender labels and workspace files remain intact.
The first new delivery includes bounded room notes and a reference to the previous
conversation so the department can inspect relevant retained work. This fallback
is an attributed handoff, not a claimed model-generated summary.

Preparation uses the existing concurrency and total-run bounds (defaults: two
departments and 300 seconds each). A compaction command gets at most 75% of that
run budget, leaving time for inspection and cleanup. Cancellation never treats a
canceled Python task as proof that a native process stopped. Roster changes are
blocked during preparation. Late results cannot rotate a canceled conversation
or unpause a subsequent Resume attempt.

## Preventing repeated room history

Each native conversation has a persisted public-history cursor. A new delivery
includes only background messages after that cursor, from at most the latest 50
candidates, with a **12,000-byte UTF-8 limit** on the serialized background array.
Long background messages are excerpted at 2,000 characters. The current input and
originating human request are supplied in full and excluded from the background
array. Historical messages remain context, never requests to replay old work.

The cursor advances only after an accepted completed delivery, to the snapshot
taken before that run. Messages arriving while a department works are therefore
available on its next delivery. Failed or acceptance-unknown deliveries do not
consume the cursor. Fresh conversations start a new cursor and handoff.

Current requests, workspace instructions and native tool output also consume
context. Pi continues its normal compaction during work; Resume provides a
separate recovery point before further requests.

## Persistence and rollout

Schema version 2 adds the preparation reservation/status records, history cursor
and previous-conversation reference. The migration supports versions 0 and 1 in
one transaction and preserves every pre-existing field. Restart always pauses the
room and marks unfinished preparation interrupted, with no automatic replay.

Back up the actual data directory while Studio is stopped before the first launch
of the updated server. Older source that supports only schema version 1 cannot
open a migrated database; use the pre-upgrade backup if reverting that source.

A private pre-upgrade snapshot was saved during this implementation at
`artifacts/context-v1-backup-2026-11-20-h2ax15lf/`: the v1 SQLite database and all
four native session files, with hashes in `manifest.json`. The directory is mode
0700 and git-ignored. It contains 123 public messages; later activity requires a
new backup. Original session files were verified against the copies and retained.

For the existing room, restart the server from the root checkout:

```bash
cd /home/zengma/department-studio
uv sync --locked
PI_CODING_AGENT_DIR=/home/zengma/.pi/agent \
  uv run --locked department-studio \
  --data-dir /home/zengma/department-studio/live-demo
```

Use the new private launch URL. A browser refresh alone cannot replace the server's
already-imported backend code. Resume prepares the existing departments using their
saved settings; no workspace change or manual SQLite/session deletion is needed.

## Verification

Final checks: **238 ordinary tests, 13 browser tests and six Node bridge tests
passed**. Ruff lint/format, JavaScript syntax and whitespace checks passed. The
synthetic integration test exercises an oversized conversation through Resume,
then confirms that one new explicit request runs with the new conversation ID
while the previous request, native transcript and workspace edit remain intact.

Deterministic backend and subprocess tests cover healthy context without inference,
compaction success/failure/ineffectiveness, over-limit fallback, null usage,
configured model/session validation, deadlines, cancellation, unconfirmed stops,
restart, stale batches, cross-connection reservations, private diagnostics, preserved
identity/history, bounded incremental prompts and cursor persistence. Browser tests
exercise progress, cancellation, retained drafts, fresh-context notes and stop gating.

A temporary SQLite backup of the actual `live-demo/room.sqlite` migrated from v1 to
v2 with all existing fields preserved and no foreign-key errors: four departments,
123 messages, paused, no active deliveries at the time of copying. Only the temporary
copy was migrated. No live model call or production server restart was performed.
