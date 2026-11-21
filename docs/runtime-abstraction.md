# Runtime abstraction, model catalog and room bridge

Status: implemented and verified with deterministic fixture runtimes. Live model
calls through the new adapters have **not** been authorized or performed.

## Why the layers are separate

Department Studio owns the room, participant identity, routing, delivery limits and
human controls. It does not own a model provider list or a native agent loop. Three
things are deliberately independent:

1. **Agent runtime** (`backend_kind`): `pi`, `claude` or `deepseek`.
2. **Model catalog entry** (`provider` / `model_id`): an OpenAI-compatible model
   declared in Studio's catalog.
3. **Native session reference**: opaque per-runtime state stored with the room
   conversation.

Changing the selected runtime starts a fresh native conversation and preserves the
room transcript, old session references and workspace files. A handoff note is
included in fresh context. It does not promise that private tool state, compaction
history or in-flight work migrates between runtimes.

## Model catalog

The bundled catalog is `backend/src/department_studio/default_models.toml`. Override
it with `--models-config PATH` or `DEPARTMENT_STUDIO_MODELS_CONFIG`. Only
`api = "openai-completions"` is accepted in this increment.

```toml
[[providers]]
id = "deepseek"
name = "DeepSeek"
api = "openai-completions"
base_url = "https://api.deepseek.com"
anthropic_base_url = "https://api.deepseek.com/anthropic" # optional translation
api_key_env = "DEEPSEEK_API_KEY"

[providers.pi_compat]
requiresReasoningContentOnAssistantMessages = true
thinkingFormat = "deepseek"

[[providers.models]]
id = "deepseek-v4-flash"
name = "DeepSeek V4 Flash"
context_window = 1000000
max_output_tokens = 384000
reasoning = true
runtimes = ["pi", "claude", "deepseek"]
```

- `base_url` is the OpenAI-compatible root. `anthropic_base_url` is used only by
  runtimes that speak the Anthropic Messages protocol (Claude Code and DeepSeek
  Harness). It is optional; without it those runtimes use their own ambient endpoint.
- `api_key_env` names a key in the environment that launches Studio. The key is
  never written to the browser, SQLite or logs. A missing key fails the delivery
  with an actionable message before a process starts.
- `pi_compat` is passed through to Pi's generated `models.json`. Keep it for
  DeepSeek reasoning history; other providers may omit it.
- `runtimes` filters which runtime can select the model. Omitting it allows all
  three.
- IDs are lowercase; context/output limits are validated; duplicate provider or
  model IDs are rejected.
- Listing models reads this file only. It does not contact a provider or start a
  runtime.

The default catalog contains DeepSeek V4 Flash and V4 Pro. No code path reads Pi's
provider catalog. A department that still references an old provider/model remains
readable, but new work fails closed with a "not configured" error until the user
chooses a configured model.

## Normalized backend contract

`backend/src/department_studio/backends/base.py` defines:

- `BackendCapabilities`: model selection, local workspace, cancellation, persistent
  conversation, room bridge and context maintenance.
- `RunRequest`: stable delivery identity, generation, department, attributed prompt,
  per-delivery bridge URL/token and optional native session reference.
- `RunOutcome`: `completed`, `failed` or `interrupted`, public text, sanitized error
  and an optional new native session reference.
- `ContextRequest` / `ContextOutcome`: an idle conversation check, never a request
  to resume old work.
- Normalized events: `started`, `progress`, `error`. Only allowlisted diagnostics
  reach the room.

`RuntimeRegistry` routes by `lead.backend_kind`, tracks which backend owns a run for
cancellation, and closes each backend once. An injected single backend serves every
runtime for tests and embedders.

`RoomService` validates the catalog selection and runtime availability before
starting work. It passes the stored native session reference into `RunRequest`; the
adapter decides whether that reference is meaningful. Cancellation always goes to
the owning adapter, and an unconfirmed stop remains visible rather than being
reported as idle.

## Adapters

| Runtime | Launch | Tools | Session | Cancellation | Room bridge |
|---|---|---|---|---|---|
| Pi | RPC child with generated `PI_CODING_AGENT_DIR` | Pi `--tools` allowlist | exact conversation UUID; Pi session file stored as a reference | `clear_queue` + `abort`, then terminate | Pi extension `send_room_message` |
| Claude Code | `claude -p --output-format stream-json` | `--tools` + `--allowedTools` | `--session-id` first run, `--resume` afterwards | close stdin, terminate process group | stdio MCP server |
| DeepSeek Harness | `dsh --profile headless --json` | per-run profile patch; Discuss disables write/edit/shell tools | `--session-id` after the first reported session | close stdin, terminate process group | stdio MCP server |

### Pi

The adapter generates a temporary `models.json` containing only the selected Studio
provider and its models, and points `PI_CODING_AGENT_DIR` at it. This prevents an
external Pi profile from supplying a different catalog or credentials. The selected
API key is passed through a per-run environment variable. Existing Pi flags,
bridge handshake, context measurement and compaction behavior are unchanged.

### Claude Code

The adapter runs Claude Code non-interactively with the selected model, a bounded
tool set, `--permission-mode dontAsk`, an explicit MCP configuration and a native
system-prompt appendix. It reads `system/init`, verifies that the `room` MCP server
loaded, and only then sends the attributed prompt on stdin. `result` supplies the
public text; `session_id` becomes the native reference. The bridge configuration
references environment variables rather than embedding the delivery token.

`ANTHROPIC_BASE_URL` is set only when the catalog provider declares
`anthropic_base_url`. The adapter sets `ANTHROPIC_AUTH_TOKEN` when a key is present.
Claude Code's own settings, hooks and authentication behavior may still apply
outside the explicit MCP/tool controls; this is a reduced tool policy, not an OS
sandbox.

### DeepSeek Harness

The adapter writes a temporary profile patch that selects
`provider: deepseek-official` and the catalog model, appends the operating
instructions, mounts `@deepseek-ai/dsh-mcp-client` for the room bridge, and (for
Discuss) disables `tool-bash`, `tool-pwsh`, `tool-jobs`, `tool-web`, `tool-subagent`,
`tool-workflow` and write/edit in `tool-fs`. Develop uses
`DSH_PERMISSION_MODE=danger-full-access`; Discuss uses `read-only`. The first run
lets the harness report its session ID; later runs pass `--session-id`. The adapter
uses the JSON `session`/`final` events and the process exit code; stderr is never
copied into the room.

This depends on the installed `dsh` version composing the documented
`headless`/`deepseek-official` profile and the named patch targets. It is verified
against a fixture, not a live harness.

### Room bridge (MCP)

`backend/src/department_studio/bridge_mcp.py` is a small stdio MCP server. It:

- validates loopback HTTP, the exact `/api/bridge/messages` path and an immutable
  delivery token from the environment;
- exposes one `send_room_message` tool with the same text/recipient limits as the
  Pi extension;
- posts JSON to the loopback bridge with `Authorization: Bearer <delivery token>`;
- returns a receipt (storage, not recipient completion) and never forwards response
  bodies or runtime errors.

The server is launched by Claude Code and DeepSeek Harness MCP configuration. The
browser owner credential is never passed to it.

## Legacy and migration behavior

- There is no fallback to a Pi provider catalog. A selection missing from Studio's
  catalog fails before a runtime starts.
- Changing workspace or runtime allocates a fresh native conversation; prior
  sessions remain stored and the room transcript is unchanged.
- Native session references are runtime-specific and are never interpreted by a
  different adapter. A runtime switch therefore starts fresh.
- Schema v3 combines context maintenance and tasks. Back up the complete private
  data directory and native sessions with Studio stopped before upgrading; do not
  downgrade afterward.

## Verification and remaining live checks

Automated coverage uses synthetic subprocesses and temporary data:

- catalog parsing, validation, filtering and credential readiness;
- registry routing, cancellation ownership and unavailable runtimes;
- Pi generated catalog isolation and RPC behavior;
- Claude init/bridge-success gate, stream parsing, resume, tool sets, error
  sanitization and cancellation;
- DeepSeek patch content, session adoption, Discuss/Develop restrictions, exit-code
  handling and cancellation;
- MCP handshake, tool call, local validation, HTTP failure sanitization and
  loopback/credential rejection.

No live Claude Code or DeepSeek Harness inference has been run. Before claiming
those adapters work live, explicitly authorize one small request per runtime and
check: the reported model, the room bridge tool, session continuation after a
restart, cancellation reaching a real process, and the absence of unrelated
credentials in the child environment.
