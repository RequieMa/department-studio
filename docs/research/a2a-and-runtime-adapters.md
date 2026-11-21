# A2A and swappable agent runtimes

Research date: 2026-11-19.
Status: findings and proposed architecture; not an approved implementation specification.
Implementation note (2026-11-21): the runtime-neutral contract, Pi/Claude Code/DeepSeek
Harness adapters and shared MCP room bridge are now implemented. A2A remains deferred.

## Recommendation

Use **Pi first behind a runtime-neutral agent backend interface**. Keep Department Studio responsible for the room, participant identity, durable messages, routing, authority and human intervention. Design a separate A2A client/server boundary for later interoperability with independently hosted agents.

A2A is a good protocol for interacting with agent services. It does not replace the machinery that launches/configures Pi, nor does it define a multi-party chat-room product. Making every local interaction A2A-native now is possible, but it adds protocol and lifecycle mapping work without eliminating either of those responsibilities.

This recommendation is based on the user's priorities: a tiny real lead-to-lead communication bootstrap, per-lead model/workspace configuration, and then using those leads to develop Department Studio itself.

## Evidence and scope

- Official A2A latest-release link resolved to **v1.0.1**. The release links to commit **3303592588e388e62e0f69f701af531d2f4e3991**, also confirmed by the Git tag reference.
- Version-source discrepancy: the tag-pinned specification's introductory navigation still labels 1.0.0 as the latest release. This appears stale relative to the release page and tag. This analysis uses the v1.0.1 tag, not that navigation label. A v1.1.0-rc tag also exists; it is not the stable release selected here.
- The specification's negotiated **wire version is 1.0**, not 1.0.1. Patch numbers do not participate in protocol negotiation.
- Read the tag-pinned specification and normative protobuf sections for messages/tasks, contexts, discovery, auth, extensions, delivery and cancellation.
- Read the installed Pi SDK, CLI integration, RPC and RPC command documentation, plus model/session examples.
- The official Python SDK latest-release page separately resolved to v1.3.1. SDK version numbers and protocol versions must not be conflated; the SDK was not installed or tested.
- Public documentation was retrieved; no project files were uploaded, credentials inspected, or Department Studio agent integration exercised. There is no runtime or protocol-conformance validation yet.

Public evidence snapshots are in `/tmp/a2a-research-aEI6bn/`. Primary-source links are listed below so this note does not depend on that temporary directory surviving.

## What A2A supplies

| Capability | Spec behavior | Relevance here |
|---|---|---|
| Agent discovery | Agent Card describes identity, skills, interfaces, security requirements and optional capabilities | Discover or register an external department/service |
| Simple exchanges | Send Message can return a direct Message | Short questions and answers need not become long-running tasks |
| Work lifecycle | Send Message can instead return a Task with status, history and artifacts | Delegate work and track its result |
| Related conversations | contextId groups related messages/tasks; taskId addresses a particular existing task | Maintain continuity with each external agent |
| Progress updates | Polling; optional streaming and HTTP webhook notifications | Show progress in the room |
| Intervention | input-required and auth-required states; cancellation request | Surface questions, authorization needs and stop requests |
| Content | Text, file references and structured content; artifacts distinguish deliverables from discussion | Exchange specifications and outputs |
| Security/interoperability | Authentication declarations, server-side authorization requirements, transport bindings and negotiated extensions | Connect agents across runtime and organizational boundaries |

A2A supports JSON-RPC, gRPC and HTTP+JSON bindings. Choosing a binding does not implement an agent runtime.

## What Department Studio must still own

### 1. Shared room semantics

The core A2A message roles describe client-to-agent and agent-to-client communication. They do not define room membership, `@department` addressing, broadcast policy, which lead should respond, cross-department commitments, or bounded discussions.

A service can build a group chat on top of A2A, and one server can expose multiple logical agents. A2A does not require a separate microservice per lead. However, our application still needs the room logic in either design.

### 2. Runtime management and configuration

An Agent Card describes what an agent service offers; it does not standardize selecting its model, setting a local repository directory, starting a native coding-agent process, or importing a Pi session into another runtime.

A future remote A2A agent may control its own model and workspace. Our UI must not pretend that every backend supports local model selection or repository access. Configuration controls must follow reported backend capabilities.

### 3. Durable records

A2A contexts may expire. Task history need not retain every message, and clients may miss informational updates while disconnected. Webhook delivery must be attempted at least once, but retries are optional and delivery is not exactly once.

Therefore, the room needs its own canonical transcript, delivery records, replay/deduplication policy and mappings to native/remote contexts. Each remote context ID is opaque and agent-scoped; do not assume it equals the room ID.

### 4. Authority and human takeover

Authentication can establish a caller identity; application policy still determines whether that caller may delegate work, modify files or spend resources. An agent message is not human authorization simply because its transport role is `user`.

A2A cancellation is explicitly not guaranteed to succeed and does not undo completed side effects. Human takeover requires Department Studio to stop new dispatch, request runtime cancellation, track whether the worker actually stopped, and prevent late results from being accepted as current work. Existing edits must remain visible for inspection rather than silently being rolled back.

### 5. Repository and integration policy

A2A does not implement Git worktrees, submodule updates, merge authority, cross-repository atomic changes or aggregate acceptance tests. A file URI also does not guarantee that a recipient can access that file. Artifact access and workspace isolation remain separate concerns.

## Proposed boundaries

### Room/application layer

Owns the stable user and lead identities, room messages, recipient routing, conversation limits, authorization, work ownership and human controls. It is deterministic infrastructure, not an AI project boss.

Keep room IDs, message IDs and lead IDs separate from Pi session IDs, runtime run IDs and future A2A task/context IDs.

### Agent backend contract

A small conceptual contract, to finalize in the design:

- Describe supported capabilities and configuration fields.
- Open or resume a conversation and return an opaque backend reference.
- Submit an addressed input with a host-assigned actor and correlation identity.
- Stream normalized public reply/progress/error/lifecycle events.
- Request cancellation and report its outcome, rather than assuming it succeeded.
- Close/disconnect cleanly.

Model listing/selection, local process ownership, native resumption, tool telemetry and workspace control are optional capabilities, not requirements every external agent must fake.

Pi-specific records stay inside the Pi adapter. A common error/event vocabulary must preserve unsupported capability, failure and uncertainty rather than flattening everything into a text reply.

### Initial local implementation: Pi RPC

If we choose a Python host, Pi's documented RPC mode is a natural boundary: a long-lived child process exchanges JSONL commands/events over stdin/stdout. Project Python remains managed through `uv`; Pi is the external agent runtime, not a Python package.

The installed docs expose:

- CLI model/provider selection and session persistence; launch with the intended working directory.
- `get_available_models` and `set_model`.
- `prompt`, `steer` and `follow_up`.
- Session inspection and switching.
- Streaming message/tool events.
- `clear_queue` and `abort`.

The TypeScript SDK is also viable if a TypeScript host is selected instead. It directly exposes per-session model, cwd, tools and persistence. Neither route requires forking Pi or modifying its internals.

Important Pi-specific details for the later implementation plan:

1. A successful prompt response means accepted/queued/handled, not completed.
2. `agent_end` can be followed by retries or queued work. Use `agent_settled` to know automatic work has ended, then inspect the outcome: settled does not mean successful.
3. Clear Pi's steering/follow-up queue before aborting for takeover. The RPC reference warns that abort can continue remaining queued messages. Also suspend the application's own dispatcher.
4. Keep stdout continuously drained and correlate command responses by request ID. Session events generally have no command ID; serialize lead runs or maintain explicit run association.
5. Do not feed untrusted peer text as native slash commands or trust a model-generated sender identity. Room inputs are data under a host-defined actor/authority envelope.
6. Use an explicit saved session per lead; two leads working in the same repository must not accidentally resume each other's most recent session.
7. A local workspace and a subprocess are not OS sandboxes. Tool permissions and credential exposure need an explicit design.

### Future external implementation: A2A

Two independently useful additions:

- **Client adapter:** let a Department Studio lead be backed by an external A2A agent.
- **Server gateway:** expose selected Department Studio leads to authorized A2A clients.

Map public messages, tasks, artifacts and capability states at this boundary. Keep room governance and local runtime configuration in Department Studio. An external client role must not be elevated to the human project lead.

Extensions can carry mutually understood additional data, but an extension understood only by our application does not magically make room semantics interoperable with arbitrary agents.

## Switching models versus switching agent runtimes

- **Model change inside Pi:** supported by its native interface; the application should define when the change takes effect and record it.
- **Runtime change, such as Pi to Codex:** preserve the department identity, room transcript and accepted decisions. Start an appropriate new native session with a deliberate handoff. Do not promise lossless migration of private tool state, compaction history or execution state.
- **Workspace change:** rebind to the intended repository/session under an explicit policy, not by silently redirecting tools while a run is active.

An abstraction makes implementations replaceable; it does not make all their capabilities or native state formats identical.

## Alternatives and trade-offs

| Approach | Benefit | Cost / limitation |
|---|---|---|
| **Native adapters now, A2A boundary later — recommended** | Smallest bootstrap; direct model/workspace/lifecycle controls; clear extensibility | Requires a small internal contract and a later A2A mapping |
| A2A service boundary from the first milestone | Proves standards-based interoperability early and unifies local/remote service calls | Still needs Pi wrappers and all room logic; adds Agent Cards, task/history/auth/transport semantics now |
| Room/UI coupled directly to Pi RPC | Shortest throwaway implementation | Leaks runtime semantics and makes later adapters and migration harder; reject for this project |

Deferring A2A is a scope recommendation, not an argument that A2A is unsuitable or only usable over the internet. If standards-based interoperability is a first-demo acceptance criterion, use the second approach deliberately.

## Verification to require later

Before claiming the bootstrap works:

- Two Pi leads with distinct saved sessions and configured workspaces exchange a real addressed message through the room.
- Different selected models are reflected in each live runtime's reported state.
- Human input and peer input remain distinguishable in authorization and audit.
- Loop limits and stop controls bound automated exchanges.
- A queued message plus cancellation does not unexpectedly start another run.
- Restart preserves the canonical room transcript and correct per-lead session mapping.
- Runtime errors are shown as errors, not successful replies.

Before claiming A2A interoperability, additionally test the selected wire version and binding, direct-message and task responses, context/task mapping, unsupported capabilities, reconnection, cancellation outcomes and authenticated access against a real independent implementation. No such tests have been run yet.

## Primary sources

1. [A2A v1.0.1 release](https://github.com/a2aproject/A2A/releases/tag/v1.0.1).
2. [Pinned specification: operations, including messages and cancellation](https://github.com/a2aproject/A2A/blob/v1.0.1/docs/specification.md#3-a2a-protocol-operations).
3. [Contexts and multi-turn interaction](https://github.com/a2aproject/A2A/blob/v1.0.1/docs/specification.md#34-multi-turn-interactions).
4. [Wire versioning](https://github.com/a2aproject/A2A/blob/v1.0.1/docs/specification.md#36-versioning).
5. [Message/history reliability limitations](https://github.com/a2aproject/A2A/blob/v1.0.1/docs/specification.md#37-messages-and-artifacts).
6. [Authentication and authorization](https://github.com/a2aproject/A2A/blob/v1.0.1/docs/specification.md#7-authentication-and-authorization).
7. [Normative Agent Card and capability model](https://github.com/a2aproject/A2A/blob/v1.0.1/specification/a2a.proto#L361-L452).
8. [Official Python SDK release inspected](https://github.com/a2aproject/a2a-python/releases/tag/v1.3.1), not installed or validated.
9. Installed Pi documentation under the installed Pi package: `docs/sdk.md`, `docs/cli-integration.md`, `docs/rpc.md`, `docs/rpc-commands.md`, `examples/sdk/02-custom-model.ts`, and `examples/sdk/11-sessions.ts`.
