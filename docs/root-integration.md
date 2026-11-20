# Root checkout integration

## Source and runtime are separate

The bootstrap repository at `.worktrees/bootstrap` was imported locally and root `main` fast-forwarded from `f7eeae0` to `b99a206`, preserving all three implementation commits. The bootstrap directory is a separate Git repository, not a linked worktree of root. `integration/bootstrap` records the imported baseline.

The subsequent source partition is in the root checkout only:

```text
backend/src/department_studio/   # Python server and Pi bridge
frontend/                       # browser HTML, JS and CSS
tests/                          # shared verification (at root)
pyproject.toml                   # root uv project and build configuration
uv.lock
```

Run all uv commands at the repository root. Wheel builds include frontend assets; source distributions include both source roots. Browser routes and API contracts are unchanged. Historical bootstrap planning/verification documents retain their original paths.

The live bootstrap source, its environment and `.department-studio/` data have not been moved, copied or changed. No runtime switch or live model test is part of this integration. Source integration alone does not move running sessions.

## Human-controlled switch (not performed)

1. Review the source/layout changes and test evidence first.
2. Pause and stop the room; wait for active leads to stop. Shut down the old Studio server normally and verify it exited.
3. With the server stopped, back up the existing private data directory and native sessions. Do not copy a live SQLite database or commit state/credentials.
4. From `/home/zengma/department-studio`, run `uv sync --locked` and start the reviewed root checkout. To retain the current room without moving data, explicitly use:
   ```bash
   uv run department-studio --data-dir /home/zengma/department-studio/.worktrees/bootstrap/.department-studio
   ```
   Use the actual existing data directory instead if the old server was started with a custom `--data-dir`, and retain its selected Pi executable/provider environment. Never run two servers against the same data directory. Starting with the default root data directory instead creates a separate empty room.
5. Use the newly printed private launch URL. The restarted room begins paused; inspect settings/history before resuming.
6. Workspace settings are not rewritten automatically. A changed workspace intentionally creates a fresh native conversation while preserving room history. Keep configured paths unless you deliberately want that change.

Keep the bootstrap checkout while any workspace or data directory references it. Deleting it, moving private state, changing selected workspaces and restarting the service require separate human decisions.

## Local verification environment

The normal uv cache lacked the locked packages. Synchronization succeeded offline using the existing project cache:

```bash
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv sync --locked
UV_CACHE_DIR=/tmp/department-studio-uv-cache UV_OFFLINE=1 uv run --no-sync pytest -q
```

This creates a separate uv-managed root `.venv`; it does not repurpose the live bootstrap environment. The cache path is environment-specific, not a required project setting.

Results for the partitioned root checkout:

- New source-layout/asset tests first failed against the old layout, then passed.
- Ordinary suite: **139 passed, 5 browser tests deselected**, including isolated installed-wheel CLI/asset serving.
- Node bridge tests: **6 passed**; frontend JavaScript syntax check passed.
- Ruff lint and format checks passed.
- `uv build` produced a source distribution and built its wheel successfully.
- No live model calls; browser end-to-end tests were not rerun for this layout-only change.
- Peer review requested from `@review`; runtime application remains pending human review/approval.
