# Department Studio

A local shared room where **you are the project lead**. Create your own departments, choose each lead's role, exact model and workspace, and address them in one persistent conversation. There are no built-in departments or autonomous AI manager.

This is the communication bootstrap described in `docs/superpowers/specs/2026-11-19-bootstrap-design.md`, extended with runtime-neutral adapters and a Studio-owned model catalog. It has a Python core, Pi/Claude Code/DeepSeek Harness adapters, SQLite persistence, and a browser interface without a frontend build step. It also includes a persistent Ongoing tasks map with human-created branches and owner-targeted instructions. A2A, worker fleets and task ownership transfer remain deferred.

**Live model-backed collaboration has not been demonstrated with the new adapters.** Automated replies are explicitly synthetic test fixtures. Pi RPC behavior was previously checked against an installed Pi; Claude Code and DeepSeek Harness adapters are verified only against deterministic fixture processes. See `docs/runtime-abstraction.md` and `docs/verification.md` for the contract, evidence and remaining live checks.

For the prepared two-department live demonstration, follow `docs/live-demo.md`.
It covers provider readiness, user-chosen setup, the explicit peer-request prompt,
and the evidence needed before calling the demonstration successful.

## Run locally

Install `uv` and at least one supported agent runtime: Pi, Claude Code, or DeepSeek Harness. The bootstrap targets POSIX hosts and was verified on Linux. The Pi adapter targets the documented RPC surface (`agent_settled`, `clear_queue`, `abort`, explicit session IDs and resource-disable options); earlier bootstrap verification used Pi 1.5.2. Claude Code and DeepSeek Harness are not live-verified in this checkout.

From the repository root:

```bash
uv sync --locked
uv run department-studio
```

Open the launch URL printed in your terminal. Its `#token=…` fragment gives that tab owner access. The browser moves the token into tab session storage, clears the fragment, and sends credentials only in Authorization headers. Keep the launch URL private; a service restart creates a new credential.

The default address is `http://127.0.0.1:8765`. Options:

```bash
uv run department-studio --port 8767 --data-dir /path/to/private/studio-data
uv run department-studio --pi-executable /path/to/pi --claude-executable /path/to/claude
uv run department-studio --deepseek-executable /path/to/dsh --deepseek-profile headless
uv run department-studio --models-config /path/to/models.toml
```

Use the exact printed address: other Host headers and browser origins are rejected. The server only accepts loopback IPs, runs one process, and never enables automatic reload. No agent runtime is started merely by opening the room. A missing runtime is reported in the department dialog; it does not prevent the others from starting.

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
3. Choose an **Agent runtime** and an exact model from Studio's catalog. There is no default model selection. Model listing reads the configured catalog only; it does not contact a provider or start an agent.
4. Save with **Discuss**, the default tool mode. Add further departments as needed, then resume the room when ready to send addressed work.

Studio owns the selectable model catalog; it does not reuse a Pi provider list or credentials. The bundled `backend/src/department_studio/default_models.toml` declares DeepSeek V4 Flash and V4 Pro through an OpenAI-compatible endpoint. Override it with `--models-config PATH` or `DEPARTMENT_STUDIO_MODELS_CONFIG`. Only `api = "openai-completions"` is accepted in this increment. Put keys in the launching environment, named by `api_key_env`; the browser never receives them. A listed model can still fail at inference time, and Studio reports that failure without substituting another model. See [runtime abstraction](docs/runtime-abstraction.md) for the schema and per-runtime translation.

Pi receives a generated, per-run `PI_CODING_AGENT_DIR` containing only the selected Studio provider, so an unrelated Pi profile cannot supply or override the catalog. Claude Code receives the model and optional Anthropic-compatible endpoint from the catalog. DeepSeek Harness receives the model through a per-run profile patch. The room bridge is a Pi extension for Pi and a stdio MCP server for Claude Code and DeepSeek Harness.

Edits to settings require the department to have no queued, running or stopping delivery. Renaming preserves its ID and native conversation; old room messages retain their original labels. Changing workspaces creates a fresh native session while preserving room history and prior session references.

Edits to settings require the department to have no queued, running or stopping delivery. Renaming preserves its ID and native conversation; old room messages retain their original labels. Changing workspaces creates a fresh native session while preserving room history and prior session references.

## Work in the room

For a copyable two-department example, see the [sample conversation](docs/sample-conversation.md). It
includes an ordinary note, a lead-to-lead request and a summary back to you;
illustrative replies are clearly separated from real model output.

An unaddressed message is a public note. Use `@handle` to request a response, or `@all` to address every enabled department. The composer previews recipients; the server validates them again. Messages sent while paused remain public and are not replayed when you resume.

Leads receive the attributed request and originating human request in full, plus bounded updates from public room history. Background context uses at most the latest 50 new messages, excerpted within a 12,000-byte limit; a persisted per-conversation cursor avoids repeating earlier snapshots. Each department keeps a distinct native conversation even when departments share a workspace or runtime.

The `send_room_message` tool posts public text and optional explicit recipient handles. Its acknowledgement confirms storage, not recipient completion. The host supplies the sender identity and accepts calls only from an active delivery's credential. Retrying the same tool call cannot duplicate a message or delivery. Final assistant text is public; mentions inside a final response do not trigger work. Private reasoning, raw tool results and complete native transcripts are not broadcast.

Each human request permits **eight deliveries total**, including the initial recipients and peer follow-ups. If a whole recipient set will not fit, the message remains visible with a notice and no partial fan-out. Self-addressing does not enqueue work. Studio permits at most two active leads and one delivery per lead. Each run currently has a five-minute deadline; these limits are not spending guarantees. A progress-aware watchdog replacing the short total deadline is [documented for later implementation](docs/watchdog-follow-up.md), not enabled in this release.

## Ongoing tasks and human decisions

The collapsible **right-hand Ongoing tasks** panel shows a branching task map (a modal drawer on smaller screens). New addressed room messages create one root per recipient; **Create subtask** adds explicit child metadata without starting execution. Existing room history is not backfilled. Selecting a node shows its public context, owner and instruction history.

Instructions target that node's stable department ID; mentions inside them do not add recipients. **Queue instruction** follows existing work without interrupting it. **Record note**, offered while paused/stopping, creates no delivery and never sends automatically on Resume. Retrying an uncertain submission does not duplicate execution. Task closure is a human action, separate from a completed run, and is blocked while linked work is queued/running/stopping.

**Run Activity** shows only explicit unresolved, currently actionable human requests—not routine run completions or completion toasts. Persisted single-choice requests present radio options and atomically record the selected choice with a public task follow-up. Request authoring is available through the **owner API only** in v1; departments do not automatically create selectors from their prose, so an empty Activity feed is normal. Closed/unavailable targets retain decision history in task details but leave the actionable feed.

See [backend/TASKS.md](backend/TASKS.md) for APIs, idempotency, lifecycle, pagination and migration details. Context maintenance and tasks now share **schema v3**: v1 adds deletion, v2 adds context checks, and v3 adds tasks. Stop writers and back up the full persistent data/native sessions before upgrading; use the same absolute data directory and do not downgrade afterward. A port-bind failure does not guarantee the database was untouched: the current CLI opens Store before binding.

## Discuss, Develop and manual continuation

**Discuss** is a reduced tool set, **not filesystem isolation**: Pi gets read/search/list plus the room tool; Claude Code gets `Read`, `Grep`, `Glob` plus the MCP room tool; DeepSeek Harness gets its read/search tools with write, edit and shell tools disabled. Files are accessed as the local OS user; the selected workspace is not a sandbox.

**Develop** adds editing, writing and shell tools. The UI requires explicit confirmation when enabling it. This authorizes local work needed for your explicit request, including project dependency and test commands. It does not grant permission to push, publish, deploy, access unrelated data, perform unrelated destructive actions, or use additional external services. Agents are instructed to ask you in the room first. These are operating rules for trusted local agents; a general shell is not a universal approval enforcement system.

Use **Pause & stop** before manual continuation. Studio blocks dispatch, cancels queued work and revokes active credentials before requesting native cancellation. Pi clears its queue and aborts; one-shot adapters close stdin and terminate their process group. Studio waits for idle/exit and escalates to process-group termination if needed. A stopping department stays unavailable until exit or idle is confirmed. Existing edits are preserved; stopping is not rollback or proof that every external side effect has stopped.

After a service restart, unfinished runs and context preparation are marked interrupted, queued work is canceled, and the room starts paused. Nothing is automatically replayed. If a previous execution outcome is uncertain, inspect its processes, workspace and native session before resuming.

**Resume room** checks every enabled department's conversation before enabling new requests. Pi context is measured and compacted with the selected model; Claude Code and DeepSeek Harness own their native compaction, so their idle check is a no-op. Pi context that is too large or cannot be compacted is replaced with a fresh conversation and bounded handoff, preserving old transcripts and workspace files. Wait for **Room running** before sending work; **Cancel resume** stops preparation. See [context maintenance](docs/resume-context.md) for the policy, migration and live-demo restart instructions.

For self-development, first save a Git baseline and select separate workspaces/worktrees for concurrent editors. Test and review proposed changes before restarting the application. The bridge extension is snapshotted at service startup, so editing its source does not change the next running-server delivery. Changes to authentication, tool permissions or cancellation controls require an explicit human request and human review. Self-development agents are not started automatically.

## Data and runtime boundary

The default `.department-studio/` directory is git-ignored and private to the local user. It contains `room.sqlite`, a process lock and `sessions/<department-id>/`. Keep it outside tracked source when choosing a custom location. A second Studio process cannot open the same data directory.

The default is relative to your launch directory. To keep departments, room history and native conversations across launches, always use the same explicit absolute `--data-dir`; switching directories/checkouts otherwise opens a different room. The local `/live-demo/` directory is also ignored, but custom locations elsewhere still need explicit exclusion. Department deletion retains history and native session references; it does not delete workspace/session files. Its schema migration runs when opening an old store, so back up with the service stopped before upgrading and do not downgrade to an older binary afterward.

SQLite owns department identity, public messages, chains, receipts and delivery state. Each runtime owns its native session files: Pi and Claude Code sessions live under the Studio data directory, while DeepSeek Harness uses its own `DSH_HOME`. A fresh child or one-shot process is launched for each delivery with the department's native session reference; its immutable runtime credential expires with that delivery. Browser owner credentials are never passed to a runtime. Studio discards raw stderr and sanitizes runtime errors instead of storing raw logs.

The application protects local roles and accidental cross-origin access. It is a trusted, single-user prototype, not a security boundary against another process with the same OS account. Back up private state with the server stopped. Never commit databases, session files or credentials.

## Verification

All Python environments, dependencies and commands use `uv`. The ordinary test suite uses deterministic backends plus fake Pi, Claude Code and DeepSeek Harness subprocesses; it does not call live models. A local MCP bridge test exercises the stdio JSON-RPC boundary against a loopback HTTP fixture.

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
