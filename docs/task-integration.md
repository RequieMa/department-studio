# Ongoing tasks — combined integration checkpoint

## Scope and source lineage

The human approved implementation and, once ready, local integration to `main` and
cleanup of the merged feature branches. The combined candidate remains isolated in
`feat/backend-tasks`, under `.worktrees/backend-tasks`.

Included source lines:

- Backend task/schema/API implementation and contract: `2dcf7fd`, `54cf1a6`.
- Reviewed RPC robustness already on `main`: `816a9f9`, incorporated by `18ff9c6`.
- Frontend map, forms and explicit-decision Activity: `0171aab`.
- Frontend actionable-only browser expectations: `0510511`.
- Frontend retained blocked/resolved decision history: `f05e255`.
- Backend boundary regression and installed-wheel checks: `440f3ac`.

`e288af0` combines these source lines. This checkpoint additionally extends genuine
browser coverage for retained decision history after resolution, closure/reopen,
owner deletion and reload. The final tested candidate SHA is recorded in the room.

## Verification

The combined source has passed:

- **224 ordinary tests** using temporary SQLite and synthetic runtimes/processes.
- **15 Chromium browser tests** against an owned local synthetic HTTP server,
  including three task-specific real-endpoint tests (no task API mocks).
- **6 Node bridge tests**, JavaScript syntax, Ruff lint/format and whitespace checks.
- Source-distribution → wheel build. Installed-artifact checks run away from the
  checkout with source-import environment overrides removed. They verify packaged
  `tasks.py`/`task_api.py`, authenticated empty task/action endpoints, the actual
  `app.js` import of `tasks.js`, the JavaScript content type and exact served asset
  bytes against the wheel, including `/tasks.js`.

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

## Merge blocker — unrelated root work

At this checkpoint root `main` still points at `816a9f9`, but has unrelated,
uncommitted runtime/context/UI work. Neither department owns that work as part of
this task integration. It has **not** been staged, stashed, discarded or overwritten.
The verified task candidate has **not** been merged into that dirty worktree.

The human or owner of those edits must reconcile them first. If reconciliation
changes `main`, integrate that new commit into the isolated candidate, resolve any
source conflicts without changing control policy, and rerun the combined checks.
Only then merge into clean root `main`, request integrated review and remove the
fully merged feature branch refs after checking their worktrees are clean/unused.
Do not force-update the checked-out `main` ref to bypass the dirty-tree safeguard.

## Release boundary

A source merge is not a live deployment. No restart, migration of live data, push,
permission/authentication/cancellation change or watchdog implementation is included.

Before a human-controlled upgrade, stop all writers and back up the entire actual
persistent directory and native sessions. Use the same absolute `--data-dir`.
Task schema v2 is additive but there is no downgrade procedure. The existing CLI
opens Store before binding, so failed startup may still have migrated a database.
See [the task contract](../backend/TASKS.md) and
[the deferred watchdog design](watchdog-follow-up.md).
