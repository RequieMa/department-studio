# Department Studio: communication bootstrap

Date: 2026-11-19.
Status: **approved**, with the user's addition that departments are named during initial setup. Runtime-neutral core, Pi RPC, local communication-first bootstrap and later A2A boundary are approved. Live model calls still require user-selected models and explicit live-test authorization.

> **Later extensions (2026-11-20/21).** This file records the approved original
> bootstrap. The implementation now differs in the following reviewed ways; where the
> body conflicts with this table, the current docs win.
>
> | Original scope | Current implementation |
> |---|---|
> | One project and one room | Multiple isolated project rooms with history/switch/delete |
> | Pi only | Pi, Claude Code and DeepSeek Harness adapters behind one contract |
> | Runtime/provider enumeration | Studio-owned OpenAI-compatible model catalog (DeepSeek V4 Flash/Pro bundled) |
> | Unaddressed human message is a public note | No-`@` message continues the last explicit addressees; explicit public-note opt-out |
> | Pi extension only | Pi extension plus stdio MCP room bridge for Claude Code/DeepSeek Harness |
> | No task board | Ongoing task map, metadata branches and explicit human decisions |
> | Three UI functions | Adds project history, records, hierarchy, folding, addressing, tasks and theme |
> | One SQLite room | One isolated SQLite database + sessions + records per project |
>
> A2A remains deferred; the watchdog and full worker/ownership transfer remain deferred.
> Current contracts: [runtime abstraction](../../runtime-abstraction.md) and
> [project rooms, records, hierarchy and addressing](../../projects-records-hierarchy.md).
> Live two-department acceptance and independent review remain outstanding; see
> [documentation status](../../documentation-status.md).

## 1. Outcome

Build a small local application in which the user configures department leads, addresses them in one room, and watches real Pi-backed leads communicate. Once that loop is demonstrated, allow the user to enable development tools and direct those same leads to improve Department Studio.

The user is the project lead. There is no AI project manager, global Router, or autonomous priority setter above the departments.

The first demonstration project was the user's Department Studio checkout, not a game or a scripted scenario.

## 2. Scope and stack

- One local user. **Current implementation:** multiple isolated project rooms, one active at a time (later extension).
- Python service using FastAPI, a single service process, and SQLite for durable local records.
- Plain HTML/CSS/JavaScript served by that service. Avoid a separate frontend build toolchain for the bootstrap.
- All Python interpreters, dependencies and commands managed through `uv`; maintain `pyproject.toml` and `uv.lock` when implementation starts.
- Pi remains an external runtime. One explicit Pi session per lead, reached through the Pi adapter.
- A small project-owned Pi extension supplies a structured room-message tool. This extension is TypeScript; the Python-only `uv` constraint does not prohibit a native Pi extension.
- Browser commands use HTTP. The initial UI refreshes room/status data every second; Pi events are consumed continuously by the backend. Token-by-token UI streaming is not required for the first demonstration.
- Bind only to loopback; do not provide public hosting, external agent access or A2A endpoints in this increment.

Alternatives considered: a separate React/Vite frontend is extensible but adds bootstrap machinery; a TypeScript host could use Pi's SDK but is not needed for the approved RPC boundary. The proposed Python service plus a small static frontend keeps the initial development surface small.

## 3. Lead configuration

A lead has a stable ID independent of its native session, and these editable settings:

- User-chosen department display name and unique user-chosen `@handle`; names are not fixed by the application.
- Department role/instructions.
- Backend kind: current implementation supports `pi`, `claude` and `deepseek` (later extension).
- Exact catalog provider and model ID; Studio owns the catalog (later extension).
- Existing local workspace/repository directory.
- Enabled/paused status.
- Permission mode: **Discuss** or **Develop**, defaulting to Discuss.

First run starts with no departments. The user names each department and assigns its handle, role, model and workspace. Backend, Frontend and QA are examples only: no department names, roles or routing are hard-coded. A department called “Foundry” can perform backend work, and “Canvas” can perform frontend work.

Display names may contain spaces and Unicode. Handles are distinct routing aliases, normalized to lowercase, and must be unique; reserve `all`, `you` and `system`. Renaming a department or handle is allowed while it has no active or queued delivery. Keep its stable ID, conversation and delivery relationships; existing messages retain the sender label recorded when posted. Only future mentions use the updated handle.

Superseded by the runtime/catalog extension: Studio owns a configurable OpenAI-compatible model catalog and translates a selection per runtime. The UI offers explicit runtime and model choices; it does not display, copy or edit API keys. A model being listed does not prove its credentials or endpoint work: show runtime failures honestly. Do not silently substitute a different model.

Validate workspace existence and canonicalize the path. Do not clone repositories or create worktrees automatically. Separate worktrees are recommended before two development-enabled leads edit the same project; the user selects their paths through the UI.

Only apply model, role, permission or workspace changes while that lead has no active or queued delivery. Model changes can preserve its explicit Pi session; role changes restart the process with the updated instructions. Workspace changes require a fresh native session rather than silently redirecting an existing conversation's tools. Preserve prior room messages and session references for audit.

Changing the backend in a future version preserves the department identity and shared decisions, not a promise of lossless native-session migration.

## 4. Room behavior

### Human messages

- An ordinary unaddressed message is visible in the room but does not wake every lead. **Current implementation:** an unaddressed human message continues the last explicit addressees; the composer offers an explicit public-note opt-out. (Later extension.)
- Recognized department mentions select recipients; `@all` explicitly addresses all enabled leads.
- The composer shows the resolved recipients before submission. Unknown handles are reported before a request is sent.
- Each submitted human request starts a conversation chain with its own correlation ID and bounded delivery allowance.
- Public visibility does not imply authority: only an authenticated human action can change lead configuration, enable development tools or pause/resume the room.

### Lead messages

- Leads receive the addressed input and a labeled snapshot of the most recent 50 public room messages, including sender identities. If older history is omitted, the prompt says so; the full transcript remains visible to the user.
- Each lead also retains its own native Pi conversation. A room ID is not a native session ID.
- A lead uses a structured `send_room_message` tool to post text and optional recipient handles. The backend authenticates the originating lead; the model cannot choose its sender identity or claim to be the human.
- A tool post with no recipients is public information only. Addressed tool posts enqueue follow-up deliveries within the originating human request's allowance.
- The lead's completed final assistant response is posted to the room as a public reply, but text mentions inside that response do not trigger more work. Do not route from raw token output, quoted mentions or hidden reasoning.
- Pi tool results, private reasoning and the entire native transcript are not automatically broadcast to other leads. Public posts and final replies are the sharing boundary.

The room-message tool returns only after the server has committed the message and its eligible deliveries, or reports a failure. Use a tool-call-derived idempotency key to avoid duplicate posts when the same call is retried. The acknowledgement means the post was stored, not that recipients finished working.

### Scheduling and limits

- At most one active delivery per lead; default global concurrency is two.
- Each human request allows at most eight lead deliveries in total, including initial recipients and lead-to-lead follow-ups. Reserve allowance transactionally when creating deliveries so concurrent posts cannot bypass it.
- If a post cannot fit all intended recipients into the remaining allowance, keep the public post but enqueue none of those recipients and show that user intervention is needed. Do not silently deliver to an arbitrary subset.
- A run has a five-minute deadline. Timeout uses the stop safeguards below for the affected lead: block redispatch, cancel its queued deliveries, invalidate its execution generation, clear native queues and request cancellation. Keep the lead unavailable until idle or process exit is confirmed; do not free it for new work merely because a deadline passed. Report interrupted/error rather than success, and leave an unconfirmed stop visibly blocked.
- No self-addressed auto-delivery and no implicit broadcast of agent messages.
- A new human request can start a new chain. Limits bound automation; they are not monetary billing guarantees.

## 5. Human control and development permissions

### Discuss mode

Allow the room-message tool and explicit native read/search/list tools. Disable shell, editing, writing, auto-loaded extensions and MCP servers. Load only the project-owned bridge extension and approved project instructions.

This is a reduced tool set, **not filesystem isolation**. Reads still run under the host OS account, and a workspace path is not a sandbox. The prototype is for trusted local use, not adversarial agents or untrusted repositories.

### Develop mode

The user explicitly enables native editing, writing and shell tools for a lead. This grants autonomy for local source edits, project dependency management and test/build commands needed by an explicit user request, not blanket approval for unrelated side effects. The UI warns that these tools run with the local account's access, not in a container. Permission cannot be elevated through the room's agent API.

Agents must ask the human in the room before pushing/publishing/deploying, accessing unrelated data, destructive actions beyond the requested work, or using additional external services beyond configured model inference. Changes to this application's authentication, permissions or cancellation controls require an explicit human request and human review before application. These are operating rules for trusted agents, not claims of comprehensive command-by-command enforcement: Develop mode exposes a general shell, and the bootstrap has no shell sandbox or universal side-effect approval engine. Disable development tools if that access is unacceptable.

Retain the same bounded room conversation mechanism. Do not install a worker fleet or allow unrelated auto-discovered tools in this increment. Human requests provide the work scope; peer discussion is contextual delegation within that scope, not authority to change global permissions.

Before self-development, save a baseline in Git and use separate workspaces/worktrees for concurrent editors. The initial implementation is not a multi-user security boundary.

### Stop and manual takeover

- Pause room: transactionally block new dispatch, cancel pending deliveries, and invalidate the current execution generations before signaling running leads.
- Clear native steering/follow-up queues, then request Pi abort. Do not allow application queues to immediately restart a stopped lead.
- Wait for confirmed idle. If it does not stop promptly, terminate the child process and report the outcome. Never label an unconfirmed stop as safe takeover.
- Late tool posts from invalidated generations are rejected; late runtime results remain diagnostic evidence, not new accepted room work.
- Preserve existing file edits. Stopping is not rollback, and subprocess cancellation is not proof that every possible external side effect has stopped.
- The user can inspect the state and do the remaining work personally, then explicitly resume discussion.

An explicit task board with transferable ownership is a later increment. The bootstrap provides stop/pause and manual continuation, not a claim that the full task-takeover workflow already exists.

## 6. Runtime adapter boundary

The core depends on a backend contract, not Pi command names or Pi message types. Its responsibilities are:

- Describe configuration/capability support.
- Open/resume a lead conversation using an opaque backend reference.
- Accept a host-attributed input and correlation identity.
- Emit normalized public response, progress, failure and lifecycle events.
- Request cancellation and report whether the runtime became idle.
- Close cleanly.

Pi's model enumeration, configuration and managed local workspace support are adapter capabilities. **Current implementation:** model listing comes from Studio's catalog, not a runtime; runtime differences are reported as capabilities. Future remote A2A agents may not expose local workspace support.

The Pi adapter must:

- Launch with an explicit workspace and per-lead session reference; never use workspace-wide “continue most recent.”
- Use exact provider/model selection and verify the runtime reports the requested model.
- Correlate command acknowledgements by request ID and continuously drain stdout/stderr without logging credentials.
- Treat prompt acceptance separately from completion. Use `agent_settled` for the end of automatic activity and inspect the final outcome; settled does not mean successful.
- Keep one submitted delivery active per lead to avoid ambiguous association of session events with requests.
- Wrap room input as attributed data, not raw native slash commands.
- Disable resource auto-loading that could add unrelated execution paths; read the installed Pi configuration/security references before implementing launch policy.
- Handle unsupported extension dialogs by rejecting/canceling them with a visible diagnostic, rather than hanging or auto-approving them.

## 7. Persistence and restart policy

Store application state outside tracked source files in a git-ignored local data directory:

- Lead configuration and configuration revision.
- Canonical room messages with stable IDs, sender, recipients, timestamp and sequence.
- Conversation chains and delivery allowance.
- Delivery records: queued, running, completed, interrupted, failed or canceled; originating message, recipient, attempt/generation and native references.
- Explicit per-lead native session references.

Pi owns its native session files; SQLite owns room and delivery state. Store message insertion and recipient enqueueing in one transaction. The UI reads persisted state, so reconnecting a browser does not depend on reconstructing transient token streams.

After service restart, show prior messages and lead configuration. Mark unfinished active work as interrupted and keep dispatch paused until the user resumes. Do not automatically repeat a model turn or shell operation whose outcome is uncertain. Pi's saved history may help the user inspect what happened; it does not establish exactly-once execution.

Per-process credentials are regenerated on restart. Do not commit databases, session files, credentials or raw runtime logs.

## 8. Local service access

- The browser's human control session and runtime bridge credentials must be distinct.
- Browser setup uses a local launch credential; do not introduce organizational accounts or invitation flows.
- Each runtime credential is scoped to that lead and current execution generation. It may post allowed room messages, not change configuration or impersonate the user.
- Reject unexpected origins and do not enable permissive cross-origin access.
- Never pass API keys to the frontend or put bridge credentials in room messages.
- This protects application roles and accidental cross-origin access. It does not isolate a development-enabled process from other resources owned by the same OS user.

## 9. UI surfaces

Keep one page with three clear functions:

1. **Leads:** list, create/edit, runtime/model/workspace selection, permission mode and status.
2. **Room:** chronological attributed messages, visible recipients, human composer with mentions and default-addressing opt-out, peer-message folding, and explicit error/limit notices.
3. **Control:** room paused/running state, pause/stop and resume actions, with stopping versus confirmed-idle states distinguished.
4. **Current extensions:** project history, durable records, department hierarchy, ongoing tasks/decisions, and a local light/dark theme.

Do not add a workflow graph editor, organization browser, marketplace or provider-login screen. Backend/frontend code can evolve after the bootstrap; visual styling is finalized during approved implementation, not by importing enterprise administration patterns.

## 10. Acceptance and verification

Automated checks use a deterministic fake backend and a fake Pi RPC subprocess. Fakes are test tools, not substitutes for the real demonstration.

Required checks:

- Empty first-run setup, custom Unicode department names and unique handles; roles are independent of names.
- Renaming preserves stable identity, session and old message attribution; future mentions resolve the new handle.
- Lead configuration validation and persistence.
- Exact recipient routing, unknown mentions and explicit broadcast.
- Human versus lead authorization on control endpoints.
- Two leads retain distinct sessions even when they reference the same repository.
- Room posts are committed before acknowledgement and duplicate tool submissions do not create duplicate deliveries.
- Per-lead serialization, global concurrency and transactional conversation limits.
- Unaddressed final responses do not cause agent reply storms.
- Cancellation clears queues, prevents redispatch and rejects stale posts.
- Runtime/provider failures, timeout and process exit are shown accurately.
- Restart preserves the room and leaves uncertain work interrupted, not blindly replayed.
- UI can create/edit leads, send an addressed message, show responses/errors and pause/resume.

Live demonstration, using models selected by the user:

1. Create two user-named departments in Discuss mode, assigning one backend and one frontend responsibilities. For example, use Foundry (`@foundry`) and Canvas (`@canvas`), but do not seed or require these names.
2. Ask the backend-responsible department to coordinate with the frontend-responsible department on adding sender-based message filtering to Department Studio, using their chosen handles.
3. Observe a real structured peer post, the recipient's response, and an agreed interface in the shared room.
4. Demonstrate stop controls and preserved history.
5. After the user explicitly enables development in separate workspaces, have the leads implement the filter endpoint/UI and tests.
6. The user reviews and integrates their changes before restarting or reloading the application.

The first implementation milestone ends at the communication/stop demonstration. Enabling development and building message filtering is the follow-on dogfooding milestone, using the same adapters and room—not a second orchestration system.

## 11. Explicit non-goals

- A2A client/server implementation or conformance claims.
- Claude Code/Codex adapters in the first increment. **Claude Code was added later; Codex remains deferred.**
- Autonomous project leadership.
- Nested worker delegation, full task board or automated ownership transfer. **A persistent task map was added later; transferable ownership remains deferred.**
- Automatic submodule maintenance, cross-repository releases or GitHub accounts.
- Browser token streaming, distributed deployment or always-on cloud hosting.
- Comprehensive sandboxing or guaranteed rollback/exactly-once external effects.

## 12. Approval record

The user approved this bootstrap scope and requested user-defined department naming at the beginning of setup. This revision makes that requirement explicit. Implementation planning can proceed; full task ownership remains deferred until dogfooding.

At design approval, no application code had been written, dependencies installed, or live model calls made for this prototype.

As of 2026-11-21, the implementation is merged to `main`; automated tests and a
built-wheel check pass. Live acceptance was attempted but not established: Pi was
blocked by a read-only config directory, DeepSeek Harness returned HTTP 401 with the
configured key, and a Claude Code smoke run did not finish in the verification
window. No successful live collaboration is claimed. See
[documentation status](../../documentation-status.md).
