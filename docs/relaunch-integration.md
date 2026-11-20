# Deletion and frontend relaunch integration — 2026-11-20

## Source included

The human requested committing the pending work and integrating the feature worktrees
into root `main` before their own relaunch. The local integration branch is
`integration/relaunch-20261120`, prepared in `.worktrees/relaunch-integration`.

It includes:

- Backend deletion `afca952` and its fresh verification record `988f71c`:
  history-preserving tombstones, revision/busy checks, transactional schema migration
  and isolated artifact verification. See [backend contract](../backend/DELETION.md).
- Reconciled frontend `4f2dd68`, including all three frontend feature branches:
  deletion UI, stabilized mentions, Markdown rendering/hardening, Enter-to-send,
  activity notifications/focus, mobile recipient wrapping and accurate working labels.
  See [frontend evidence](frontend-integration.md).
- A real-HTTP deletion browser regression in `tests/test_browser_deletion.py`, covering
  stale owner-tab edits, explicit retry, successful deletion, retained history/draft,
  idempotent receipt, roster removal, `@all` exclusion, rejected explicit mentions and
  busy-delivery rejection. Existing Store/API tests also cover late runtime replies.
- An explicit `/live-demo/` ignore rule. No runtime state is included in source commits.

The older dirty root UI draft was preserved, not discarded or merged over the repaired
frontend. It is stored in local Git stash commit
`31b315e4f0a05f1cc73173530e9800c23d709abd`, named
`Preserve superseded root UI draft before reviewed relaunch integration 2026-11-20`.
Only the three frontend files and `tests/test_browser.py` were stashed. It contains no
`live-demo/` data. Inspect it with `git stash show -p <commit>` if needed; do not blindly
apply it over the integrated fixes. Feature worktrees and commits were retained.

## Combined verification

The combined source and real-endpoint regression passed:

- **182 ordinary tests**, including Store/API/service, schema migration and isolated
  installed-wheel import/hash/HTTP asset verification.
- **12 browser tests** against the synthetic HTTP server with temporary SQLite data:
  11 frontend tests plus the new real-endpoint deletion test.
- Ruff lint and formatting; JavaScript syntax; all **6 Node bridge tests**.

Python commands use the uv-managed integration environment with inherited `PYTHONPATH`,
`PYTHONHOME` and `VIRTUAL_ENV` removed. The existing offline dependency cache is
`/tmp/department-studio-uv-cache`; the existing matching browser cache is
`/tmp/department-studio-playwright`. These paths are local conveniences, not product
requirements. An initial browser run without the browser-cache setting failed before
tests started because the default cache lacked the locked Chromium version. Selecting
the already-installed matching cache resolved that environment issue without downloads.
The first new deletion test used the wrong confirmation text (omitted `@`); correcting
the test to match the UI contract made the real-endpoint test pass.

Reproduce from the chosen checkout, with its uv environment synchronized:

```bash
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
node --test tests/test_bridge_extension.mjs
node --check frontend/app.js
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv build

# Terminal 1: synthetic backend, temporary application data; no live models
uv run --no-sync python -m tests.browser_server --port 18766
# Terminal 2: same checkout/environment and an unused test-server port
PLAYWRIGHT_BROWSERS_PATH=/tmp/department-studio-playwright \
STUDIO_BROWSER_ORIGIN=http://127.0.0.1:18766 uv run --no-sync pytest -m browser -q
```

The integration review recommended preserving the superseded root draft, merging the
final frontend tip with the backend candidate, and passing combined verification before
updating main. Automated checks do not establish live model acceptance or comprehensive
assistive-technology/real-IME testing. No new long-term memory feature is included.

## Human-controlled relaunch — do not skip the backup

Source integration does not restart Studio or migrate the live room. The human retains
control of relaunching. Before starting this deletion-inclusive version:

1. Pause/stop the room, wait for work to stop, shut down the old server normally and
   confirm it is no longer writing. Never run two servers against one data directory.
2. Back up the **actual entire persistent data directory**, including native sessions,
   while the service is stopped. Do not copy a live SQLite database or commit backups.
3. From root, synchronize with `uv sync --locked` and launch with the **same absolute
   `--data-dir` used previously**, preserving the selected Pi executable/provider
   environment. Do not substitute the default or a historical example path blindly.
   Opening a different directory gives a different room and can look like lost departments.
4. Opening a v0 store automatically migrates it to v1 (`leads.deleted_at`). The old
   bootstrap binary does not understand tombstones: **a binary-only downgrade is unsafe**.
   Recovery/restore must account for history written after upgrade; do not casually
   overwrite the upgraded data with an older backup.
5. Open the new private launch URL, confirm the retained departments/history and paused
   room, then resume only when ready. A browser reload alone is not a backend restart.

No live database/session inspection, live model inference, restart, backup, copy or
migration was performed by this integration task. Launch/migration remains a separate
human action after reviewing this warning.
