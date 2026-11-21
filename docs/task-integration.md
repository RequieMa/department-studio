# Ongoing tasks — combined integration and runtime reconciliation

## Scope and source lineage

The human approved implementation and local integration to `main`. The task feature
is now integrated on the `integration/runtimes-tasks` branch together with the
runtime abstraction and Studio-owned model catalog.

Integrated source lines:

- Backend task/schema/API implementation and contract: `2dcf7fd`, `54cf1a6`.
- Reviewed RPC robustness already on `main`: `816a9f9`, incorporated by `18ff9c6`.
- Frontend map, forms and explicit-decision Activity: `0171aab`.
- Frontend actionable-only browser expectations: `0510511`.
- Frontend retained blocked/resolved decision history: `f05e255`.
- Backend boundary regression and installed-wheel checks: `440f3ac`.
- Admin's documentation-only `main` update: `a5462a0`, incorporated by `57c43f7`.

`e288af0` combines the task/RPC/frontend source lines. This checkpoint additionally extends genuine
browser coverage for retained decision history after resolution, closure/reopen,
owner deletion and reload.

Root `main` advanced with context maintenance while the task branch was isolated.
The reconciliation on `integration/runtimes-tasks`:

- keeps context maintenance as schema v2 and moves tasks to schema v3;
- makes the v2 step idempotent so a released context-only database and the
  short-lived task-only v2 shape both upgrade safely;
- combines bounded incremental room history with the immutable task snapshot;
- keeps the approved actionable-only Activity panel while retaining the context
  preparation notes and controls;
- adds the Pi/Claude Code/DeepSeek Harness runtime registry and Studio model catalog.

Changing a department's runtime now allocates a fresh native conversation, because
native session references are runtime-specific. Room history, old session references
and workspace files are retained.

## Verification

The combined source has passed:

- **316 ordinary tests** using temporary SQLite and synthetic runtime processes,
  including catalog, registry, Claude Code, DeepSeek Harness and MCP bridge fixtures.
- **17 Chromium browser tests** against an owned local synthetic HTTP server,
  including three task-specific real-endpoint tests and the runtime/model dialog.
- **6 Node bridge tests**, JavaScript syntax, Ruff lint/format and whitespace checks.
- Source-distribution → wheel build. Installed-artifact checks run away from the
  checkout with source-import environment overrides removed. They verify packaged
  `tasks.py`, `task_api.py`, the runtime adapters, the default model catalog, the
  MCP bridge, the actual `app.js` import of `tasks.js`, JavaScript content types and
  exact served asset bytes against the wheel, including `/tasks.js`.

No live Claude Code or DeepSeek Harness inference was run. Those adapters are
verified against deterministic fixture processes only.

Browser servers use temporary data, `/bin/true` rather than a live Pi executable,
an explicit test credential and an available loopback port. Only the test runner's
own server process group is terminated, and shutdown is awaited. No live server,
model, persistent database or native session is accessed.

Earlier combined browser failures were not ignored: two legacy tests expected
routine completion notifications, which contradict the approved actionable-only
Activity requirement. The frontend follow-up updates those expectations. A task
select test was aligned to the existing stable select ID. The task boundary tests
also reproduced and fixed an empty optional decision-source ID reaching SQLite as
a foreign-key failure; it now returns a validation error with no partial writes.

## Reconciliation record

The previous blocker was root work that changed the same seven paths. That work is
now committed on `main` (`dc026c5`), and the reconciliation resolves the real
semantic conflicts rather than merging around them:

- schema v2 collision: context maintenance is v2, tasks are v3, and the v2 step
  repairs either pre-merge shape;
- `service.py`: bounded incremental history plus task snapshots in the same attributed
  prompt;
- `frontend/app.js`: actionable-only Activity plus context preparation and the new
  runtime/model selector;
- migration, browser and packaging tests updated for v3 and the new endpoints.

The source merge is not a live deployment. No running room, persistent database or
native session was modified during implementation.

## Release boundary

A source merge is not a live deployment. No restart, migration of live data, push,
permission/authentication/cancellation change or watchdog implementation is included.

Before a human-controlled upgrade, stop all writers and back up the entire actual
persistent directory and native sessions. Use the same absolute `--data-dir`.
Combined schema v3 is additive but there is no downgrade procedure. The existing CLI
opens Store before binding, so failed startup may still have migrated a database.
See [the task contract](../backend/TASKS.md) and
[the deferred watchdog design](watchdog-follow-up.md).
