# Department Studio Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (the installed Pi adaptation) to implement this plan task-by-task. Steps use checkbox syntax for tracking. All Python commands use `uv`. The implementation design is approved; execution workspace/strategy is selected at handoff.

**Goal:** Let one human create user-named departments, assign models/workspaces, and run bounded real Pi-backed conversations in one local room, ready for user-directed self-development.

**Architecture:** A FastAPI/SQLite room core owns identity, messages, routing, authority and delivery state. A runtime-neutral backend contract delegates execution to Pi RPC; a small Pi extension posts structured room messages back to an authenticated endpoint. Persistent per-department conversation IDs survive renames and process restarts; A2A is deferred.

**Tech Stack:** Python 3.12+, uv, FastAPI, uvicorn, SQLite, plain browser JavaScript/CSS, a TypeScript Pi extension, pytest/pytest-asyncio/httpx, Ruff, and Python Playwright for browser verification.

---

## Approved references and constraints

- `AGENTS.md`
- `docs/superpowers/specs/2026-11-19-bootstrap-design.md`
- `docs/research/a2a-and-runtime-adapters.md`

No seeded Backend/Frontend/QA departments and no fixed mapping from names to behavior. First-run setup is empty. Display names support Unicode and spaces; handles are lowercase routing aliases. Names, handles, instructions, model and workspace are user choices.

No live inference in automated tests. Use synthetic model metadata and explicitly test-only backends. Real model calls wait for the user's model choices and authorization. A no-prompt Pi RPC handshake can verify the installed transport without claiming real model collaboration.

## File ownership and structure

| Files | Responsibility / owner task |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | Toolchain, dependencies and exclusions / 1 |
| `src/department_studio/__init__.py`, `config.py` | Package and validated local server settings / 1 |
| `src/department_studio/domain.py`, `store.py` | Models, identity, SQLite transactions and durable routing / 2 |
| `src/department_studio/backends/base.py`, `service.py` | Backend boundary, scheduling and stopping / 3 |
| `src/department_studio/backends/pi.py`, `backends/rpc.py`, `pi_extension.ts` | Pi implementation and room bridge / 4 |
| `src/department_studio/security.py`, `api.py`, `cli.py` | Authentication, HTTP endpoints and local launcher / 5 |
| `src/department_studio/static/index.html`, `app.js`, `style.css` | First-run configuration and room UI / 6 |
| `tests/` | Task-owned tests; shared fixtures only changed by their owner |
| `README.md`, `docs/verification.md` | Operation, limits and verified versus unverified behavior / 7 |

Keep modules focused; separate RPC transport from Pi lifecycle and SQLite storage from scheduling. Package the static assets and Pi extension so the installed wheel works outside the source tree.

## Shared contracts (freeze before independent implementation)

### Data and validation

`LeadCreate` contains `name`, `handle`, `role`, `provider`, `model_id`, `workspace`, `enabled` (default true), and `permission` (`discuss` by default or `develop`). `Lead` additionally contains `id`, `conversation_id`, `revision` and runtime status. Never derive IDs from names or handles.

- Display name: trimmed, 1–80 characters, Unicode permitted.
- Handle: normalize to lowercase, match `[a-z][a-z0-9_-]{0,31}`, unique; reject `all`, `you`, `system`.
- Role: trimmed, 1–8000 characters; independent of name.
- Provider/model: nonempty exact identifiers, at most 200 characters each; no implicit fallback.
- Workspace: resolve an existing directory. Keep validation independent of model invocation.
- Message text: nonempty, at most 32000 characters.
- Settings updates: optimistic `revision`; reject while deliveries are queued, running or stopping. A workspace change creates a fresh conversation ID. Renames preserve the existing conversation ID.

`RoomMessage` records `id`, `sequence`, `sender_kind` (`human`, `lead`, `system`), `sender_id`, immutable `sender_name` and `sender_handle` snapshots, `text`, recipient IDs, chain ID and timestamp. A final assistant response never automatically routes based on its text.

Delivery states are `queued`, `running`, `stopping`, `completed`, `failed`, `interrupted`, `canceled`. Each delivery has a unique ID, chain ID, message ID, lead ID, generation, timestamps and sanitized error. SQLite also stores room pause state and each chain's reserved delivery count.

### Backend interface

Create these dataclasses/protocol in `backends/base.py`; core code must not import Pi modules:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from department_studio.domain import Lead

@dataclass(frozen=True)
class BackendCapabilities:
    model_selection: bool
    local_workspace: bool
    cancellation: bool
    persistent_conversation: bool

@dataclass(frozen=True)
class ModelOption:
    provider: str
    id: str
    name: str

@dataclass(frozen=True)
class AgentEvent:
    kind: Literal["started", "progress", "error"]
    message: str

@dataclass(frozen=True)
class RunRequest:
    id: str
    generation: int
    lead: Lead
    prompt: str
    bridge_url: str
    bridge_token: str

@dataclass(frozen=True)
class RunOutcome:
    state: Literal["completed", "failed", "interrupted"]
    text: str = ""
    error: str | None = None
    native_session_ref: str | None = None

Emit = Callable[[AgentEvent], Awaitable[None]]

class AgentBackend(Protocol):
    def capabilities(self) -> BackendCapabilities: ...
    async def list_models(self, workspace: Path) -> list[ModelOption]: ...
    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome: ...
    async def cancel(self, run_id: str) -> bool: ...
    async def close(self) -> None: ...
```

The ellipses above are Python Protocol declarations, not incomplete implementations. Local model/workspace support is documented as a capability; do not force future remote adapters to pretend they own a local directory.

### HTTP contract

All `/api/*` requests require a browser owner credential except the narrowly scoped bridge endpoint. Responses must never include provider headers, API keys or runtime tokens.

| Method/path | Request / response |
|---|---|
| `GET /api/state` | `{paused, leads, messages, deliveries}`; include all persisted messages initially; client reconciles by ID without replacing active forms |
| `GET /api/models?workspace=...` | `{models:[{provider,id,name}]}` from Pi metadata, without making an inference request |
| `POST /api/leads` | `LeadCreate` → persisted Lead |
| `PATCH /api/leads/{id}` | Complete editable settings + expected `revision` → updated Lead |
| `POST /api/messages` | `{text}`; server resolves human mentions → stored message + recipient IDs + delivery/limit notices |
| `POST /api/room/pause` | Block dispatch, cancel queued work, invalidate active generations and start stopping → current state |
| `POST /api/room/resume` | Resume dispatch only; do not resurrect canceled/interrupted work |
| `POST /api/bridge/messages` | Runtime-only Bearer credential, `{call_id,text,recipients:[handle]}` → `{message_id,recipient_ids,notice}` after commit |

Use HTTP 401 for absent/invalid credentials, 403 for valid credentials of the wrong role or unexpected Origin, 409 for busy/revision/stale-generation conflicts, and 422 for invalid fields/unknown recipients. Plain domain exceptions map to these responses in `api.py`; do not import FastAPI into `store.py`.

The owner token is generated at launch, never passed to Pi. Provide a local URL with a fragment token; browser JavaScript moves it into tab session storage and clears the fragment. Use the token only in Authorization headers, not query strings. Restrict the Host/Origin to the configured loopback service and render untrusted text with `textContent`.

## Task 1: uv foundation and local configuration

**Create:** `pyproject.toml`, `.python-version`, `src/department_studio/__init__.py`, `config.py`, `tests/test_config.py`. Update `.gitignore`. Generate `uv.lock` with uv.

- [ ] Verify current Git status and selected execution branch/workspace. Do not overwrite `.vscode/settings.json`.
- [ ] Define packaging and tool settings:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "department-studio"
version = "0.1.0"
description = "A user-led room for configurable agent departments"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
department-studio = "department_studio.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/department_studio"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["browser: browser integration tests", "live: explicitly authorized live runtime tests"]
addopts = "-m 'not browser and not live'"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] Add dependencies through uv:

```bash
uv python pin 3.12
uv add fastapi uvicorn filelock
uv add --dev pytest pytest-asyncio httpx ruff playwright
uv sync --locked
```

- [ ] Write tests before the configuration implementation. `Settings` exposes `host` (default `127.0.0.1`), `port` (8765), `data_dir` (resolved `.department-studio`), `pi_executable` (`pi` resolved through PATH), `max_concurrency` (2), `max_chain_deliveries` (8), `run_timeout_seconds` (300) and `stop_timeout_seconds` (10). Expose `origin` as the computed loopback HTTP URL. Reject nonpositive limits, invalid ports and non-loopback binding.
- [ ] Run `uv run pytest tests/test_config.py -q`, observe missing behavior, implement `Settings`, and rerun until green.
- [ ] Use private, git-ignored `.department-studio/` for DB/sessions and a file lock to prevent two service processes opening the same application data directory. Test lock contention without starting Pi.
- [ ] Run `uv run ruff check .` and commit only this task's files after review.

## Task 2: user-named departments and transactional room storage

**Create:** `domain.py`, `store.py`, `tests/test_leads.py`, `tests/test_store.py`.

- [ ] Write the custom-name and stable-identity regression first:

```python
from department_studio.domain import LeadCreate
from department_studio.store import Store

def test_user_names_and_rename_preserve_identity(tmp_path):
    store = Store(tmp_path / "room.sqlite")
    assert store.list_leads() == []
    lead = store.create_lead(LeadCreate(
        name="星图 Studio", handle="atlas", role="Build the backend",
        provider="test", model_id="model-a", workspace=str(tmp_path),
    ))
    post = store.post_public_reply(lead.id, "Contract recorded")
    renamed = store.update_lead(
        lead.id, lead.revision, {"name": "Foundry", "handle": "forge"},
    )
    assert renamed.id == lead.id
    assert renamed.conversation_id == lead.conversation_id
    assert store.list_messages()[0].id == post.id
    assert store.list_messages()[0].sender_name == "星图 Studio"
    assert store.resolve_mentions("@forge review this") == [lead.id]
```

- [ ] Run `uv run pytest tests/test_leads.py -q`; implement validated models and SQLite-backed CRUD to satisfy it.
- [ ] Add separate failing tests for duplicate/reserved handles, normalized case, names unrelated to roles, invalid workspaces, optimistic revision conflicts, busy lead edits, and workspace changes creating new conversation IDs. Implement each behavior and rerun.
- [ ] Implement transactional tables for leads, room state, chains, messages, deliveries and bridge idempotency receipts. Use SQLite foreign keys, WAL, bounded busy timeout and explicit transactions. Keep synchronous transactions free of awaits.
- [ ] Write routing tests: unaddressed human message has no recipients; enabled `@all` expansion; explicit disabled/unknown handles fail; email addresses do not become mentions; public assistant text never dispatches. Mention matching uses standalone `@handle` tokens, case-insensitively, not substring search against display names.
- [ ] Write tests proving message insertion + delivery reservation are atomic, eight-delivery allowance never partially fans out, and the same bridge call returns its saved receipt without re-enqueueing.
- [ ] Write tests that pause/invalidate rejects stale bridge posts; canceled/interrupted work is not revived on resume; restarting preserves message snapshots and starts paused.
- [ ] Run `uv run pytest tests/test_leads.py tests/test_store.py -q`; inspect schema/diff and commit after review.

## Task 3: backend-neutral scheduling and stopping

**Create:** `backends/__init__.py`, `backends/base.py`, `service.py`, `tests/fakes.py`, `tests/test_service.py`.

- [ ] Implement the shared backend declarations above, then a test-only fake with controllable start/release/cancel barriers. Keep fake models and responses out of production modules.
- [ ] Write failing service tests that start two departments with arbitrary names, verify independent conversation IDs, and assert maximum two active runs and one run per lead.
- [ ] Implement `RoomService` with a dispatcher, persisted delivery claims, active-run tracking and an injected backend. Each prompt contains the addressed input, authenticated sender identity, originating human request, and up to 50 labeled public messages. Say when older messages are omitted.
- [ ] Verify final replies are persisted once without parsing their mentions. Expose failure/timeout separately from successful completion. Empty final text may complete a delivery but must not fabricate a reply.
- [ ] Write stop tests before implementing stop logic: mark room paused/invalidate first, revoke bridge tokens, cancel pending work, request backend cancellation, and keep an unconfirmed stop unavailable. Resume does not replay old work.
- [ ] Implement timeout using the same per-lead invalidation/stop lifecycle, not simply `wait_for` plus freeing the slot. A canceled coroutine is not proof that its subprocess stopped.
- [ ] Test races: stop during claim, bridge post during stop, late final output after invalidation, timeout followed by a new human message, and shutdown while two runs are active.
- [ ] Run `uv run pytest tests/test_service.py -q` and the store tests. Commit after spec and quality reviews.

## Task 4: native Pi RPC adapter and structured room bridge

**Create:** `backends/rpc.py`, `backends/pi.py`, `pi_extension.ts`, `tests/fixtures/fake_pi.py`, `tests/test_rpc.py`, `tests/test_pi.py`, `tests/test_bridge_extension.mjs`.

Before implementing harness integration, read the relevant installed docs/examples in full. Root: `/home/zengma/.local/share/qgenie-cli/pi-cli/.npm-global/bin/`. Required: `docs/cli.md`, `cli-integration.md`, `rpc.md`, `rpc-commands.md`, `json.md`, `rpc-extension-ui.md`, `extensions.md`, `configuration.md`, `security.md`, relevant model/provider references, `examples/rpc-client.ts`, `examples/extensions/hello.ts` if present, and a custom-tool example identified in `examples/extensions/README.md`. Follow related references needed for the APIs actually used. Do not read credential values or update Pi.

- [ ] Create a fake JSONL Pi child. Launch test Python through `["uv", "run", "--project", project_root, "--no-sync", "python", fixture_path]`, not a global interpreter.
- [ ] Write transport tests for split byte chunks, CRLF, literal Unicode line separators inside JSON, mismatched command IDs, malformed records, EOF, stderr draining, rejected prompt and startup failure. Implement LF-only record framing and correlated pending requests.
- [ ] Write lifecycle tests: accepted prompt is not completion; `agent_end` is not settled; provider failure followed by settled is failed; handled-without-run prompts do not hang; queued input cannot survive clear-queue/abort; cancellation waits for idle or confirmed process exit.
- [ ] Use a fresh RPC child for each delivery, reopening the department's explicit persisted conversation. This bounds each child's bridge credential to one immutable delivery/generation while retaining conversation history. It avoids changing environment credentials inside an already-running lead.
- [ ] Build argv without a shell. Select exact model/provider, explicit session ID and session directory, explicit workspace cwd, resource-disabling flags and a sole project bridge extension. Choose tools from Discuss/Develop policy. Load approved project instructions deliberately; do not turn project trust into implicit permission for unrelated extensions or MCP servers.
- [ ] Keep runtime/model configuration controls inside this adapter. Project Python remains uv-managed; Pi runs as the installed external executable.
- [ ] Before prompting, request runtime state and verify model selection. Prompt text is an attributed data envelope, never a raw room slash command. Extract public final assistant text only; never broadcast thinking or raw tool results.
- [ ] Implement model enumeration using a no-prompt, no-tool RPC process; project only `{provider,id,name}` into `ModelOption`. Never expose raw model definitions/headers or use a model invocation as a metadata probe.
- [ ] Register `send_room_message` in the project extension with text and recipient-handle arguments. Pi accepts ordinary JSON Schema parameters, so use a plain schema and type-only Pi imports for this small bridge; do not vendor host-provided Pi/TypeBox packages. Its HTTP callback uses per-delivery URL/credential supplied by the host. Derive `call_id` from the tool invocation, not model arguments. Await committed acknowledgement, surface non-2xx errors and propagate cancellation. Do not let tool arguments choose actor, role, run generation or credentials.
- [ ] Test the extension with a mocked Pi registration API and local test HTTP server; verify payload, credential scoping, idempotency key, failures and abort handling. Do not invoke a model.
- [ ] Close stdin for graceful shutdown; bound waiting and escalate to process-group termination when needed. Record uncertainty honestly if termination cannot be confirmed. Never claim rollback of existing edits.
- [ ] Run `uv run pytest tests/test_rpc.py tests/test_pi.py -q` and `node --test tests/test_bridge_extension.mjs`. Commit after review.

## Task 5: authenticated HTTP application and launcher

**Create:** `security.py`, `api.py`, `cli.py`, `tests/test_api.py`, `tests/test_security.py`, `tests/test_packaging.py`.

- [ ] Write tests against an app factory injecting a test backend and temporary Store. Require owner authentication for all control/data endpoints, accept only runtime credentials at the bridge endpoint, and reject cross-role token use.
- [ ] Implement the HTTP contract above. Snapshot endpoints include no secrets or raw native transcripts. Translate validation/conflict/runtime errors to structured, sanitized responses.
- [ ] Test bridge sender spoofing, expired generation, repeated call IDs with different bodies, unexpected Origin/Host, missing Authorization, invalid JSON and busy configuration edits. A reused idempotency key with different content must return a conflict, not silently acknowledge altered content.
- [ ] Implement owner credentials held in server memory and separate random runtime credentials bound to active delivery/generation. Never pass the owner credential into child environment variables. Persist no raw credentials in SQLite.
- [ ] Implement loopback CLI startup, data-directory lock, explicit Pi executable override, private data-directory permissions and graceful service shutdown. Default to port 8765; fail clearly if unavailable. Print a fragment-authenticated local URL; never enable uvicorn auto-reload during self-development.
- [ ] Serve packaged static assets and resolve the packaged extension path independently of current working directory.
- [ ] Run `uv run pytest tests/test_api.py tests/test_security.py tests/test_packaging.py -q` and the earlier suites. Commit after review.

## Task 6: first-run department setup and shared room UI

**Create:** `static/index.html`, `static/app.js`, `static/style.css`, `tests/test_browser.py`, `tests/browser_server.py`.

Visual direction: a quiet studio workbench, not an enterprise dashboard or marketing landing page. Cool silver background `#eef2f6`, white work surfaces `#ffffff`, ink `#203044`, muted text `#566779`, teal action `#12675d`, warning `#9a4523`. A narrow department roster and wide conversation area encode the actual interaction; stack on mobile. The signature is user-named department nameplates with stable identity colors and explicit recipient labels. Use local/system font stacks, no CDN dependency, restrained nested surfaces, subtle custom-eased focus/entry transitions and reduced-motion support. Avoid fabricated statistics, hard-coded example departments and unnecessary navigation.

- [ ] Start a test-only server with deterministic backend metadata, and write a browser test that expects the empty “Name your first department” state. Run it before building the UI and observe the missing interface.
- [ ] Implement the static shell and create/edit form: name, handle, role, workspace, model selection, enabled and Discuss/Develop controls. No automatic department creation or first model selection. Model listing is an explicit action using the chosen workspace.
- [ ] Add a browser test creating `星图 Studio / @atlas` and `Canvas / @canvas`, assigning different roles/models; rename the first to `Foundry / @forge` and assert ID/session continuity through API state.
- [ ] Implement one-second snapshot reconciliation without replacing focused inputs or erasing an unsent draft. Stop overlapping polls, handle reconnect and retain scroll position unless the user is already at the newest message.
- [ ] Implement human composer mention preview using handles, with server-authoritative validation. Display original sender snapshots, current roster names, recipient labels and delivery status separately. Render messages as text, not executable HTML.
- [ ] Test that sending `@forge` dispatches to the renamed department, an unknown old handle is rejected, unaddressed posts do not start work, and text resembling HTML is displayed literally.
- [ ] Implement pause/resume and visible stopping/failure/limit notices. Confirm Develop mode with an explicit local-access warning; never imply it is sandboxed.
- [ ] Verify keyboard labels, focus visibility, modal focus/close, mobile layout and reduced motion. Capture desktop/mobile screenshots and review actual rendered output.
- [ ] Use the webapp-testing helper through uv. First run `uv run python /home/zengma/.claude/skills/webapp-testing/scripts/with_server.py --help`; then use its documented server lifecycle options with the test server and `uv run pytest -m browser`. Because the UI polls, wait for a stable visible state rather than an unbounded network-idle wait.
- [ ] Run browser and Python suites; commit after review.

## Task 7: end-to-end verification, packaging and operator documentation

**Create/update:** `README.md`, `docs/verification.md`, packaging tests and this plan's progress checkboxes.

- [ ] Add an integration test where the fake RPC child uses the real authenticated bridge HTTP endpoint, producing an addressed post and a second department reply. This verifies the actual transport/application path while explicitly remaining a synthetic inference test.
- [ ] Add service-restart and browser-reconnect tests proving configuration, immutable message attribution and paused recovery survive. Ensure two leads sharing a repository never reuse the same conversation ID.
- [ ] Run fresh verification:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
node --test tests/test_bridge_extension.mjs
uv run pytest -m browser -q
uv build
```

Expected: all selected checks pass; browser tests do not silently skip missing dependencies. Install Chromium with `uv run playwright install chromium` if needed and permitted, or report the precise browser blocker.

- [ ] Verify the wheel contains static files and the extension; smoke-test its CLI from a temporary directory in a uv-managed environment, without inference.
- [ ] If available, perform a no-prompt installed-Pi RPC handshake with unrelated extensions/MCP disabled, then shut down. Record exact Pi version and command/event support. Do not treat this as a live collaboration demonstration.
- [ ] Document `uv sync --locked`, `uv run department-studio`, the local launch URL, user-named setup, model configuration errors, Discuss/Develop access, pause/recovery behavior and data location.
- [ ] Document the live acceptance path with user-selected names/models; require explicit permission before calls. Separate “automated tests,” “installed Pi handshake,” and “live multi-model collaboration” evidence. If the last has not run, say so prominently.
- [ ] Obtain final spec-compliance review, then quality review; fix important findings with regression tests. Run the complete relevant checks again after fixes.
- [ ] Summarize verified behavior, remaining live checks, launch instructions and source paths. Do not start self-editing agents or push to a remote without user direction.

## Execution order and review gates

Tasks 1–3 are sequential and establish the shared contracts. Tasks 4 and 5 may run in parallel only with disjoint file ownership and frozen contracts; Task 6 can build against those contracts but its end-to-end tests wait for integration. Task 7 follows all implementations.

Every task uses red → green → review. First review requirements, then quality. Workers must not change shared contracts silently or modify another task's files. Keep changes on a feature branch or an approved isolated worktree, not the planning baseline branch.

## Plan self-review

- [x] Spec coverage: setup/naming → 2/6; persistence/routing → 2; limits/stop/recovery → 3; runtime/bridge → 4; authority/local access → 5; UI → 6; packaging/live evidence → 7.
- [x] Latest addition: no seeded departments; arbitrary names/roles; stable rename identity; historical sender snapshots tested.
- [x] Pi boundary: model selection is separate from runtime selection; sessions persist while per-delivery processes scope credentials.
- [x] Deferred scope stays deferred: A2A, nested workers, full task ownership, multi-repository automation and hosted deployment.
- [x] Test commands use uv for all Python, including fake subprocesses and browser helpers.
- [x] No unresolved design placeholders; internal helper names may be chosen within each task without changing the frozen external contracts.

## Progress

- [ ] Task 1 — uv foundation and configuration
- [ ] Task 2 — department identity and transactional storage
- [ ] Task 3 — scheduling and stop lifecycle
- [ ] Task 4 — Pi adapter and bridge
- [ ] Task 5 — API, security and launcher
- [ ] Task 6 — browser UI
- [ ] Task 7 — integrated verification and documentation
