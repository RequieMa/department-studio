# Frontend integration verification — November 20, 2026

> **Historical evidence (2026-11-20).** This candidate was later integrated and
> superseded by task/project/records/hierarchy/theme work. Do not use its 11-browser-test
> counts as current. See [documentation status](documentation-status.md).


## Candidate

The `feat/frontend-activity-notifications` worktree integrates the shared
mention/deletion/Markdown history, `feat/frontend-delete-ui` hardening, and
`feat/frontend-enter-send`. The source candidate verified here is `adb4aa8`.
This record is not evidence that root main or the running service uses it.

Changes retained and repaired:

- Caret-aware mentions with persistent dismissal across polling and blur.
- Safe Markdown rendering and history-preserving deletion confirmation UI.
- Enter sends; Shift+Enter inserts a newline; Ctrl/Cmd+Enter remains supported.
  Composition, repeated keydown, pending submission and failed drafts are covered.
- Completion activity, silent initial baseline, historical handle attribution,
  bounded retention with an explicit overflow/non-success notice, one row per
  delivery lifecycle, and preserved button focus when new rows arrive.
- Wrapped multi-recipient header at 390px rather than clipping an expanded @all.
- Running deliveries say “working”, not “typing”; running is not typing telemetry.
- Python browser tests use a bounded callback wait instead of unsupported
  JavaScript-style `expect.poll`; the browser file is Ruff-formatted.

## Verification performed

Using the root uv-managed environment, offline, with Chromium installed at
`/tmp/department-studio-playwright`:

- Six targeted browser test functions passed with in-memory static assets and
  mocked API responses (mentions, activity lifecycle/focus, mobile recipients,
  Enter-send, deletion confirmation, Markdown).
- Full `pytest -m browser tests/test_browser.py -q`: **11 passed in 32.01s**.
  The server was `tests.browser_server`, launched from this frontend worktree on
  an isolated loopback port, with source PYTHONPATH pointing into this worktree.
  It used a temporary data directory and synthetic runtime, and was stopped
  after the tests. No production service, private runtime state, or live model
  was used.
- `ruff check tests/test_browser.py`, `ruff format --check tests/test_browser.py`,
  `node --check frontend/app.js`, and `git diff --check` passed.
- Synthetic desktop/mobile screenshots were captured in git-ignored `artifacts/`
  and inspected. Desktop capture includes the message arrival animation; it is
  not a pixel-baseline approval. Mobile recipient clipping has a geometry test.

The deletion test mocks the DELETE API. This candidate's backend baseline still
lacks the separate deletion endpoint/migration. **The deletion UI must be
integrated with `feat/backend-deletion` before application.** These frontend
results do not establish combined real-endpoint deletion correctness.

## Final integration and relaunch gates

- Reconcile root's older dirty UI draft without losing unrelated work; do not
  blanket-stage private `live-demo/`, native sessions, generated bridges or locks.
- Integrate backend deletion and rerun combined browser/API/migration/packaging
  verification, including actual deletion and history preservation.
- Human review and relaunch are separate. No authentication, permission or
  cancellation behavior was changed by these frontend repairs.
- Use the same explicitly chosen absolute data directory to retain departments
  and conversations. Do not migrate or copy a live database during verification.
- Real screen-reader/IME-device testing, comprehensive visual review, and live
  model acceptance remain separate from these deterministic checks.
