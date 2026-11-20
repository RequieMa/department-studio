# Department Studio

A local shared room where **you are the project lead**. Create your own departments, choose each lead's role, exact model and workspace, and address them in one persistent conversation. There are no built-in departments or autonomous AI manager.

This is the communication bootstrap described in `docs/superpowers/specs/2026-11-19-bootstrap-design.md`. It has a runtime-neutral Python core, a Pi RPC adapter, SQLite persistence, and a browser interface without a frontend build step. A2A, worker fleets and task ownership boards are deferred.

**Live model-backed collaboration has not been demonstrated.** Automated replies are explicitly synthetic test fixtures. Independent subagent spec and quality reviews were unavailable; the user authorized continuing TDD directly. See `docs/verification.md` for evidence and remaining checks.

For the prepared two-department live demonstration, follow `docs/live-demo.md`.
It covers provider readiness, user-chosen setup, the explicit peer-request prompt,
and the evidence needed before calling the demonstration successful.

## Run locally

Install `uv` and configure the external Pi runtime. The bootstrap currently targets POSIX hosts and was verified on Linux. This implementation was checked against Pi **1.5.2**, including a no-prompt RPC and bridge-registration handshake. The adapter requires the documented `agent_settled`, `clear_queue`, `abort`, explicit session IDs, and resource-disable options.

From the repository root (`/home/zengma/department-studio`):

```bash
uv sync --locked
uv run department-studio
```

Open the launch URL printed in your terminal. Its `#token=…` fragment gives that tab owner access. The browser moves the token into tab session storage, clears the fragment, and sends credentials only in Authorization headers. Keep the launch URL private; a service restart creates a new credential.

The default address is `http://127.0.0.1:8765`. Options:

```bash
uv run department-studio --port 8767 --data-dir /path/to/private/studio-data
uv run department-studio --pi-executable /path/to/pi
```

Use the exact printed address: other Host headers and browser origins are rejected. The server only accepts loopback IPs, runs one process, and never enables automatic reload. Pi is not started merely by opening the room.

## Source layout

- `backend/src/department_studio/`: HTTP API, domain/storage, scheduling and runtime adapters. The Pi bridge is backend integration code, not browser code.
- `frontend/`: browser HTML, JavaScript and CSS; communicates through `/api/` only. No frontend build step is required.
- `tests/`: backend, bridge, packaging and browser integration tests.
- `pyproject.toml` and `uv.lock`: shared root Python tooling; no second environment is needed under `backend/`.

The backend serves `frontend/` in editable checkouts. Wheels bundle the same assets under `department_studio/static/`, so an installed CLI also works outside the repository. Frontend/backend remain one same-origin application; this split does not change authentication, permissions or stop behavior.

For the archived bootstrap room and its restore process, see [root checkout integration](docs/root-integration.md). For the subsequent deletion/UI integration, combined test evidence and required pre-relaunch backup, see [relaunch integration](docs/relaunch-integration.md).

## Configure departments

1. Choose **Add department**. Enter any display name, a unique handle, and the department's role/instructions. Names support Unicode. Handles use lowercase letters, digits, `_` and `-`; `all`, `you` and `system` are reserved.
2. Click **Browse folders**, navigate to an existing local directory, and choose **Use this folder**. The picker browses folders on the machine running Studio and includes Home, Project folder, parent navigation and a name filter. Studio fills the workspace path and deliberately includes that directory's root `AGENTS.md`. It does not clone repositories or create worktrees.
3. Click **Load models**, then explicitly select a provider/model pair. There is no default model selection. Model listing requests metadata without sending a model prompt.
4. Save with **Discuss**, the default tool mode. Add further departments as needed, then resume the room when ready to send addressed work.

Studio reuses Pi's configured providers and credentials; it has no key editor or provider login screen. If no models appear, first check that Studio and your Pi TUI use the same `PI_CODING_AGENT_DIR` and that Pi can create configuration locks there. The initial empty model list in this coding environment was traced to read-only Pi configuration directories (`EROFS`); QGenie was already configured. Follow `docs/live-demo.md` to launch with the inspected QGenie configuration from your normal terminal. A listed model can still fail at inference time, and Studio reports that failure without substituting another model.

Auto-loaded extensions, MCP servers, skills, prompt templates, themes and context discovery are disabled. Only Studio's bridge extension is loaded. Providers supplied exclusively by other Pi extensions are therefore unavailable under this policy; use a supported configured provider instead. `--offline` suppresses unrelated discovery/update traffic; it does not make model inference offline.

Edits to settings require the department to have no queued, running or stopping delivery. Renaming preserves its ID and native conversation; old room messages retain their original labels. Changing workspaces creates a fresh native session while preserving room history and prior session references.

## Work in the room

For a copyable two-department example, see the [sample conversation](docs/sample-conversation.md). It
includes an ordinary note, a lead-to-lead request and a summary back to you;
illustrative replies are clearly separated from real model output.

An unaddressed message is a public note. Use `@handle` to request a response, or `@all` to address every enabled department. The composer previews recipients; the server validates them again. Messages sent while paused remain public and are not replayed when you resume.

Leads receive the attributed request and originating human request in full, plus bounded updates from public room history. Background context uses at most the latest 50 new messages, excerpted within a 12,000-byte limit; a persisted per-conversation cursor avoids repeating earlier snapshots. Each department keeps a distinct Pi conversation even when departments share a workspace.

The `send_room_message` tool posts public text and optional explicit recipient handles. Its acknowledgement confirms storage, not recipient completion. The host supplies the sender identity and accepts calls only from an active delivery's credential. Retrying the same tool call cannot duplicate a message or delivery. Final assistant text is public; mentions inside a final response do not trigger work. Private reasoning, raw tool results and complete native transcripts are not broadcast.

Each human request permits **eight deliveries total**, including the initial recipients and peer follow-ups. If a whole recipient set will not fit, the message remains visible with a notice and no partial fan-out. Self-addressing does not enqueue work. Studio permits at most two active leads and one delivery per lead. Each run has a five-minute deadline; these limits are not spending guarantees.

## Discuss, Develop and manual continuation

**Discuss** allows Pi's read, grep, find and list tools plus room messages. This is a reduced tool set, **not filesystem isolation**. Files are accessed as the local OS user; the selected workspace is not a sandbox.

**Develop** adds editing, writing and shell tools. The UI requires explicit confirmation when enabling it. This authorizes local work needed for your explicit request, including project dependency and test commands. It does not grant permission to push, publish, deploy, access unrelated data, perform unrelated destructive actions, or use additional external services. Agents are instructed to ask you in the room first. These are operating rules for trusted local agents; a general shell is not a universal approval enforcement system.

Use **Pause & stop** before manual continuation. Studio blocks dispatch, cancels queued work and revokes active credentials before requesting native cancellation. It clears Pi's queue, requests abort, waits for idle/exit, and escalates to process-group termination if needed. A stopping department stays unavailable until exit or idle is confirmed. Existing edits are preserved; stopping is not rollback or proof that every external side effect has stopped.

After a service restart, unfinished runs and context preparation are marked interrupted, queued work is canceled, and the room starts paused. Nothing is automatically replayed. If a previous execution outcome is uncertain, inspect its processes, workspace and native session before resuming.

**Resume room** checks every enabled department's conversation before enabling new requests. Healthy context is retained; large history is compacted with the selected model. Context that is too large or cannot be compacted is replaced with a fresh conversation and bounded handoff, preserving old transcripts and workspace files. Wait for **Room running** before sending work; **Cancel resume** stops preparation. See [context maintenance](docs/resume-context.md) for the policy, migration and live-demo restart instructions.

For self-development, first save a Git baseline and select separate workspaces/worktrees for concurrent editors. Test and review proposed changes before restarting the application. The bridge extension is snapshotted at service startup, so editing its source does not change the next running-server delivery. Changes to authentication, tool permissions or cancellation controls require an explicit human request and human review. Self-development agents are not started automatically.

## Data and runtime boundary

The default `.department-studio/` directory is git-ignored and private to the local user. It contains `room.sqlite`, a process lock and `sessions/<department-id>/`. Keep it outside tracked source when choosing a custom location. A second Studio process cannot open the same data directory.

The default is relative to your launch directory. To keep departments, room history and native conversations across launches, always use the same explicit absolute `--data-dir`; switching directories/checkouts otherwise opens a different room. The local `/live-demo/` directory is also ignored, but custom locations elsewhere still need explicit exclusion. Department deletion retains history and native session references; it does not delete workspace/session files. Its schema migration runs when opening an old store, so back up with the service stopped before upgrading and do not downgrade to an older binary afterward.

SQLite owns department identity, public messages, chains, receipts and delivery state. Pi owns its native session files. A fresh Pi child is launched for each delivery with the department's explicit conversation ID; its immutable runtime credential expires with that delivery. Browser owner credentials are never passed to Pi. Studio discards raw stderr and sanitizes runtime errors instead of storing raw logs.

The application protects local roles and accidental cross-origin access. It is a trusted, single-user prototype, not a security boundary against another process with the same OS account. Back up private state with the server stopped. Never commit databases, session files or credentials.

## Verification

All Python environments, dependencies and commands use `uv`. The ordinary test suite uses deterministic backends and uv-launched fake Pi subprocesses; it does not call live models.

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
node --test tests/test_bridge_extension.mjs
uv build
```

The extension tests require Node.js with native TypeScript stripping; this verification used Node 22.22.3. Browser tests require Chromium:

```bash
uv run playwright install chromium
```

Start the **test-only** server in one terminal, then run browser tests in another:

```bash
# Terminal 1: synthetic metadata/replies, temporary application data
uv run python -m tests.browser_server

# Terminal 2
uv run pytest -m browser -q
```

Set `PLAYWRIGHT_BROWSERS_PATH` consistently for installation and tests if using a custom cache. Screenshots are written to git-ignored `artifacts/`. For a live acceptance run, select the real departments/models yourself and explicitly authorize inference; the verification document gives the acceptance sequence.
