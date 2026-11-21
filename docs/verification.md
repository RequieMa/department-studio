# Bootstrap verification and current checkpoint

> **Document status:** the early sections below are historical bootstrap evidence from
> November 19–20 (including a `.worktrees/bootstrap` checkout that no longer exists).
> The **current** checkpoint is the `Current runtime/catalog/project reconciliation`
> section at the bottom. For document-by-document status, see
> [documentation and plan status](documentation-status.md).

**Independent spec-compliance and quality reviews have not been performed. Live
model-backed Department Studio collaboration has not succeeded.** These are
outstanding acceptance activities, not passing test results.

## Current live-attempt record — November 21, 2026

A bounded live attempt was made after backing up the real data directory. The live
room was **not** migrated, restarted or modified.

- Backup: `artifacts/live-demo-pre-live-2026-11-21-232350/` (git-ignored, mode 0700,
  SHA256SUMS). SQLite `integrity_check` = `ok`; schema v3; 5 departments, 180
  messages, 116 deliveries, 8 source/backup files.
- Pi smoke: failed before inference because the default Pi agent directory is
  read-only (`EACCES` creating `settings.json.lock`/`auth.json.lock`). This is a local
  configuration-environment blocker, not a model rejection. Studio's generated
  per-run Pi directory avoids the default directory, but a full Studio live run was
  not completed.
- DeepSeek Harness smoke: copied the headless profile to a writable temporary
  `DSH_HOME`, then the configured key returned HTTP 401 (`Authentication Fails`).
  No successful model turn.
- Claude Code smoke: did not finish within the 120-second verification window and
  was stopped. No result was accepted as success.

No live collaboration, records tool call, cancellation, resume-after-restart or
provider acceptance was established. A future attempt needs a writable Pi config
directory, a valid DeepSeek key, and a Claude Code path that completes a one-word
smoke call. See [runtime abstraction](runtime-abstraction.md) for the contract.

## Automated results

The application checks passed after the regression fixes below, including the
workspace folder picker. The Node bridge tests and CLI/HTTP wheel smoke results
are retained from the earlier bootstrap verification; those implementations did
not change in this increment.

| Check | Result |
|---|---|
| `uv sync --locked` | Passed; environment matches `uv.lock` |
| `uv run --locked ruff check .` | Passed |
| `uv run --locked ruff format --check .` | Passed; 33 Python files formatted |
| `uv run --locked pytest -q` | **137 passed**, 5 browser tests deselected |
| `node --test tests/test_bridge_extension.mjs` | **6 passed** |
| `node --check src/department_studio/static/app.js` | Passed |
| `uv run --locked pytest -m browser tests/test_browser.py -q` | **5 passed**; no missing-dependency skips |
| `uv build` | Built source distribution and wheel |
| Wheel contents | Current folder-listing module, static UI assets and Pi bridge match their source files |
| Wheel smoke tests | Static assets and bridge included; CLI help and authenticated HTTP launch work outside the repository in a uv-managed environment; unavailable ports fail clearly |
| Git whitespace check | Passed |

Verification used uv-managed Python 3.12.13, Node 22.22.3 and headless Chromium 159.0.8154.6 on Linux. Project dependencies are pinned in `uv.lock`.

An ordinary-suite run concurrent with Chromium completed 137 tests but reported
one teardown error in
`test_split_utf8_crlf_unicode_separators_and_correlated_ids`: fixture process
cleanup exceeded its 0.3-second stop deadline. The same test passed alone, then
the entire ordinary suite passed without Chromium running (137 passed in
22.00 seconds). No RPC lifecycle code or timeout was changed for the picker.

The ordinary suite covers:

- Empty setup, arbitrary Unicode names/roles, handle validation, stable identity/session preservation on rename, immutable message attribution, and fresh sessions after workspace changes.
- Explicit routing, ordinary public notes, enabled `@all`, unknown/disabled recipients, email-address handling, final-response non-routing and self-delivery prevention.
- Atomic message/delivery transactions, concurrent allowance reservations, all-or-none fan-out, idempotency receipts and conflicts for changed retry bodies.
- Two concurrent leads, one delivery per lead, bounded recent context, human-scope attribution, timeouts, token revocation, late results and confirmed/unconfirmed stops.
- Strict JSONL framing, split UTF-8/CRLF records, Unicode separators, correlated responses, malformed output, EOF, stderr draining, startup failure, prompt rejection and delayed settling.
- Exact Pi model/session verification, distinct per-lead sessions, permission-specific tool flags, disabled resource discovery, mandatory bridge readiness, metadata-only enumeration and private-content exclusion.
- Browser versus runtime authorization, sender spoofing, Host/Origin validation, safe error responses, stale generations, optimistic edits and paused restart recovery.
- Owner-only directory listing, hidden and Unicode folder names, canonical symlink targets, empty folders, root navigation, invalid paths and sanitized access errors. Files are excluded and listing does not start a runtime.
- A fake Pi subprocess using the real authenticated HTTP bridge to address a second lead, whose final response completes the same persisted chain. This uses real subprocess/HTTP/SQLite paths with **synthetic inference**.
- Actual fixture-process cancellation through the room service, including adapter bookkeeping and temporary bridge-copy cleanup.

The Node tests register the real TypeScript extension against a mock Pi API and a local HTTP server. They verify its schema, immutable credential, tool-derived idempotency key, awaited acknowledgement, HTTP failures, cancellation, loopback restriction and readiness signal. They do not invoke a model.

## Browser and visual verification

The browser suite creates `星图 Studio / @atlas` and `Canvas / @canvas` with independent roles/models, renames the first department, addresses its new handle, rejects its old handle and verifies historical attribution. It also checks public-only notes, literal HTML rendering, focused form/draft preservation across polling, explicit Develop consent, stop confirmation, offline reconnect, tab reload and mobile dialog focus.

A separate browser case verifies that an uncertain recovered execution is not labeled confirmed idle. This case injects the recovered HTTP snapshot; storage/restart behavior is verified separately by the ordinary suite.

Two folder-picker cases navigate real directories, choose an empty Unicode
workspace, filter names and render HTML-like names literally. They check that
Cancel preserves the workspace/model, selecting a different workspace resets the
model, saving preserves the lead ID while starting a fresh conversation, and
mobile error recovery and Escape restore focus. The existing configuration tests
also select workspaces through the picker.

Desktop and mobile screenshots were captured and visually inspected:

- `artifacts/empty-desktop.png`
- `artifacts/room-desktop.png`
- `artifacts/room-mobile.png`
- `artifacts/folder-picker-desktop.png`
- `artifacts/folder-picker-mobile.png`

The artifacts are git-ignored and contain synthetic test conversations. Browser tests used the installed webapp-testing lifecycle helper:

```bash
uv run --locked python /home/zengma/.claude/skills/webapp-testing/scripts/with_server.py \
  --server 'uv run --locked python -m tests.browser_server' --port 8766 \
  -- uv run --locked pytest -m browser tests/test_browser.py -q
```

Within the restricted development environment, uv's cache and interpreter-install directories were under `/tmp`, `UV_LINK_MODE=copy` was set, and Chromium was installed under `/tmp/department-studio-playwright`. Standard commands in the README can use the operator's normal writable uv/Playwright directories.

## Installed Pi handshake

Installed version: **Pi 1.5.2**. Two no-prompt RPC processes were checked: one for metadata only, and one loading a private snapshot of the real bridge extension with a verification-only credential.

The launch policy used:

```text
pi --mode rpc --no-approve --no-extensions --no-mcp --no-skills
   --no-prompt-templates --no-themes --no-context-files --offline
   --no-session --no-tools
```

The bridge case also supplied an explicit `-e` path to the copied extension. Both processes accepted `get_state`, `get_available_models`, `clear_queue` and `abort`, reported idle with zero pending messages, and exited with confirmation. The extension emitted `department-studio-bridge-ready-v1`, confirming registration from the copied path.

**Historical provider-listing limitation.** During the original bootstrap, the installed Pi returned zero available models under the resource policy. Inspected Pi settings named an external provider/model as their saved default; explicit probes still returned an empty list and a placeholder model, and filtered native diagnostics identified `EROFS` while creating the `settings.json` lock. That finding did not establish missing provider configuration or bad credentials.

The current build no longer reads Pi's provider catalog. Studio's own catalog supplies selectable models, and Pi receives a generated per-run agent directory. The historical external provider is not referenced by current source, tests or default configuration. See [runtime abstraction](runtime-abstraction.md) and the current verification summary below.

No `prompt` command was sent to installed Pi. This handshake does not verify provider inference, live `agent_settled` events, real lead-to-lead model reasoning or development tool execution. Their transport/lifecycle handling is covered by deterministic fixtures and the installed Pi references.

## TDD and controller self-review

Tests were run failing before implementing configuration, domain/storage, scheduling, Pi transport/lifecycle, bridge callbacks, HTTP/security and the browser interface. Additional regressions were observed failing and then fixed during controller review:

- Denied process-group termination must remain unconfirmed; it cannot free a running department.
- A missing or failed bridge must prevent a model prompt.
- Unsupported native dialogs need a specific safe diagnostic.
- Event consumers must not hang after a transport failure.
- Confirmed stops and never-started queued work need accurate persisted notices.
- Recovery with uncertain prior execution must not claim confirmed idle.
- Opening a fragment launch URL in an existing tab must establish access and clear the fragment.
- A short stop deadline must not prematurely fail slow startup. A combined subprocess/browser run exposed the timing problem; a deterministic slow-start regression reproduced it. Startup now uses its RPC deadline.
- Bridge edits during self-development must not be picked up by a running server. Each delivery loads a private copy of the bytes captured at service startup.
- An empty workspace must be rejected instead of implicitly selecting the server's working directory.

For the folder-picker follow-up, eight API tests first failed with missing-route
404 responses, and two browser tests first failed because the Browse folders
control was absent. After implementation the API file passed all 23 tests and
the browser file passed all five tests. The picker preserves department drafts,
uses the existing owner authentication and Host/Origin checks, and cancels stale
navigation requests. Directory access runs outside the async event loop.

`docs/sample-conversation.md` now provides copyable prompts for an ordinary note,
one lead-to-lead handoff and a summary back to the human. Replies are labeled as
illustrative examples. The document asks the user to substitute their own handles
and select models; it does not seed departments, send messages or invoke models.

The controller checked the implementation against the approved spec and reviewed the code and rendered UI. These checks do not replace the missing independent reviews.

## Missing independent reviews

Worker startup failed before any worker completed a task or review:

- Codex worker initialization was blocked by its read-only state directory.
- The configured Pi worker model had no authenticated matching provider.
- The alternate reviewer failed authentication with HTTP 401.

The user explicitly authorized **“Continue TDD here and report the missing independent reviews.”** Direct implementation continued under that instruction. No per-task independent spec or quality review, nor final independent spec or quality review, is claimed. Per-task review/commit gates remain unchecked in the plan; implementation is consolidated in a local commit for review.

## Remaining live acceptance

The user selected live-demo preparation as the next step. The production server
was checked with a separate `.department-studio/live-demo` data directory. Its
authenticated state endpoint confirmed an empty, paused room. A Playwright check
verified fragment authentication, the empty setup screen, Discuss as the default,
and model loading with no mutating HTTP requests or browser errors. The rendered
setup was inspected in git-ignored `artifacts/live-demo-setup.png`. The empty model
list was traced to the read-only configuration failure described above. No prompt
was sent. The temporary server was stopped so the user can launch from their normal
terminal. The concrete catalog/runtime setup and conversation sequence is in
`live-demo.md`; all live-inference checks below remain pending.

After the user chooses and configures real models and explicitly authorizes inference:

1. Start Studio and create two departments with user-selected names, roles, models and existing workspaces. Keep both in Discuss initially.
2. Resume and send one addressed request asking a lead to use `send_room_message` to consult the second lead. Verify both real responses, attributed peer delivery and distinct sessions. An ordinary note must not start another run.
3. Pause during authorized work and verify confirmed idle/exit, rejection of late posts and no replay on resume. Inspect any edits or other side effects personally.
4. Restart the service, use the new launch URL, verify durable attribution and paused recovery, then send a fresh request only when ready.
5. After independent review, save a Git baseline, select separate workspaces and explicitly enable Develop only for a narrow self-development request. Test and review changes before restarting the running application. Authentication, permission and cancellation changes require an explicit human request and review.

No live collaboration, unrestricted application agents, self-development run, A2A implementation or deployment was started as part of this verification.


## Current runtime/catalog/project reconciliation — November 21, 2026

The combined branch passed:

- 350 ordinary tests with temporary SQLite, synthetic backends and fixture Pi,
  Claude Code and DeepSeek Harness subprocesses.
- 21 Chromium browser tests against the owned synthetic server, including task
  branches/decisions, the runtime/model dialog, project history/switch/delete,
  records, hierarchy toggling, peer-message folding, default addressing and dark mode.
- 7 Node bridge-extension tests, Ruff lint/format and JavaScript syntax checks.
- A real-database **copy** migrated from schema v3 to v4 with all 5 departments,
  180 messages and 116 deliveries preserved; hierarchy backfilled to a complete graph.
- Source-distribution to wheel build and installed-artifact checks, including the
  packaged default catalog, runtime adapters, MCP bridge and task assets.

No successful live model call, persistent production migration or service restart
was performed. The bounded attempts and blockers are recorded above; the Claude Code
and DeepSeek Harness adapters remain live-unverified. Their observable boundaries and
remaining acceptance checks are listed in [runtime abstraction](runtime-abstraction.md)
and [live demo](live-demo.md).
