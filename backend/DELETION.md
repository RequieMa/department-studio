# History-preserving department deletion

> **Status (2026-11-21):** the HTTP/routing contract remains current and is now
> project-scoped (each project has its own Store). The schema account below started
> at v0/v1; current databases are at v4. See [documentation status](../docs/documentation-status.md).

## HTTP contract

`DELETE /api/leads/{id}?revision=N` uses the existing owner credential and origin checks.
There must be exactly one positive decimal revision (at most 19 digits); fractional,
missing, repeated or invalid values return 422. Runtime credentials cannot delete.

- 200: `{id, revision, deleted_at}`. The first deletion increments the revision once.
- Repeating deletion of a tombstone returns its saved receipt with no further mutation;
  the revision precondition applies only to the active-to-deleted transition.
- 409: stale revision or queued/running/stopping deliveries. Wait for work to finish or
  use the existing room Pause and wait for confirmed stop; there is no department Stop.
- 404: unknown ID. Subsequent PATCH and direct public-reply writes reject tombstones.

`/api/state.leads` excludes tombstones but retains disabled departments. Explicit
mentions of deleted recipients fail atomically; `@all` omits them. Historical sender
and recipient labels, department IDs, messages, deliveries, receipts, conversations
and native session references remain intact. The current handle stays reserved,
case-insensitively. Aliases released by an earlier rename are not newly reserved.
No workspace or native-session files are removed. There is no restore or purge API.

## Concurrency and lifecycle

Deletion, update, message enqueue and delivery claim share `BEGIN IMMEDIATE`.
Deletion cannot cancel queued work or make an unconfirmed stop appear idle. Roster
reads materialize candidate IDs before reading retained records, tolerate a concurrent
tombstone, and filter it out instead of raising a spurious NotFound. This is not a
promise of a globally point-in-time snapshot across multiple Store connections.

Future workers, waiting-for-input workflows and pending continuations must extend
all busy/dispatch checks before activation. This increment does not implement them
and does not change authentication, execution permissions or cancellation behavior.

## Schema and rollout

The current baseline is `PRAGMA user_version=4`: v1 adds deletion, v2 context
maintenance, v3 tasks, and v4 hierarchy/default addressing. Opening v0 transactionally
initializes the baseline, adds deletion, context, task and hierarchy state, and sets
v4 in one transaction. Fresh databases follow the same path; reopening v4 performs no
schema initialization. Unknown future versions are rejected before schema or
persistent journal-mode writes. Failed migrations roll back and close their database
connection.

Tests generate temporary v0 databases from `tests/fixtures/schema_v0.sql`; no deployed
room database is used. This code is not authorization to migrate or restart the live app.
A rollout needs separately approved downtime and backup. **Never open migrated data
with the old bootstrap executable:** it does not recognize tombstones or enforce the
new version guard. A binary-only downgrade is unsafe; any recovery/restore operation
requires its own reviewed procedure accounting for post-upgrade history.

## Verification boundary

Store/API/migration tests cover busy and stale failures, repeat receipts, retained
history/files, routing rejection, transactional rollback, future-version refusal,
and separate-connection deletion races. Packaging tests remove inherited Python
import paths and virtual-environment selection, use an isolated uv environment with
the current uv-managed Python version, and verify installed module/asset hashes
against the built wheel. They also compare HTTP-served assets with wheel contents.

These checks do not establish combined browser integration with the separate frontend
candidate. Real-endpoint browser verification and independent review remain required
before any conditional local merge; deployment and live migration remain separate.

### Fresh backend verification — 2026-11-20

Verified backend source commit `afca952` in its own uv-managed worktree environment,
using the existing offline cache and temporary test data only:

```bash
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv sync --locked
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv run --no-sync pytest -q
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv run --no-sync ruff check .
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv run --no-sync ruff format --check .
node --test tests/test_bridge_extension.mjs
node --check frontend/app.js
```

Inherited `PYTHONPATH`, `PYTHONHOME` and `VIRTUAL_ENV` were removed for the test
invocation so another checkout/environment could not shadow the candidate.

Historical result at this increment: **182 ordinary tests passed; 5 browser tests
deselected**, Ruff lint/format, 6 Node bridge tests and JS syntax. Current verification
is 350 ordinary, 21 Chromium and 7 Node tests with schema v4 and project isolation;
see [verification](../docs/verification.md). No live model call, server restart or
production migration has succeeded.

Combined frontend/backend browser verification is still a separate integration gate;
these results are not evidence that the pending frontend candidates are accepted.
