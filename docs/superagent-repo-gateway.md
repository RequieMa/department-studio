# Superagent-per-repository gateway — validation

Status: **validated from the local dsh-superagent source and DSH docs; not implemented.**
This document tests the idea that each GitHub repository is bound to its own
`dsh-superagent`, while Department Studio only displays the resulting conversations
and files issues when work should start.

## Verdict

The idea is **directionally sound for offloading repository work**, but it is not a
drop-in "show each superagent's chat" integration. Three corrections matter:

1. **One superagent serves one GitHub repository.** A multi-repository project needs
   one superagent profile/process per repository, each with its own state directory,
   port, profile, worker slots and backup/upgrade lifecycle.
2. **Its conversation surface is GitHub Issues/PRs (or Feishu), not a chat API.** The
   management API can read health, threads, tickets and settings and can retry/stop
   tickets, but it has no "send a chat message" endpoint. Agent replies are GitHub
   comments/PRs; the app must mirror GitHub comments to show the full conversation.
3. **There is no generic idle/spin watchdog.** Superagent has worker slots,
   Assignment/Report stages, retry/attention, input-delivery retries, evaluation
   timeouts, background-work limits, a health board, `scripts status` and an hourly
   health-check recipe. That is valuable supervision infrastructure, but an external
   supervisor still has to detect a dead process, stale polling, stuck tickets or
   repeated spinning across profiles.

A2A is not required for this topology. GitHub Issues/PRs are the integration protocol;
A2A would only matter for external, independently hosted agent services.

## Evidence

### One repository per superagent

- `package.json` describes "a proactive agent for **one GitHub repository**".
- `docs/006-deployment.md` resolves one `repository: owner/name` on the GitHub Source;
  `src/deployment.ts` validates one repository and the agent's push access.
- `src/sources/github.ts` configures one `repository` and one agent CLI; it polls that
  repository's notifications and optional repository-wide streams.
- Multiple repositories therefore mean multiple profiles/instances:
  `dsh --profile superagent-<repo>`, distinct `stateDir`, distinct panel port,
  distinct worker pool, and separate backups. They may share an agent GitHub account,
  but that needs explicit verification.

### GitHub Issues/PRs are the work protocol

- The GitHub Source observes new Issues, PRs, comments and default-branch CI when the
  corresponding switches are on; mentions and follow-ups reach Tickets.
- A Ticket is created by Eval/admission under the project Policy; the worker executes
  in its own Session and directory; it replies through the Source channel (GitHub
  comments/PRs) and reports to the Ticket.
- Requests normally arrive through the agent account's notifications. An issue body
  edited later to add a mention is not received; post a new comment instead.
- The agent account must have push access and be signed into a dedicated `gh` wrapper.
  The current `gh-agent` wrapper exists but is **not logged in**; the main `gh` session
  is a personal account (`RequieMa`) and is not the superagent's agent identity.
- The current superagent state DB has no tickets/threads/triggers and no configured
  repository; its profile panel port is not listening. It is not ready to accept work.

### Management API is read/control, not chat

`src/app/api.ts` exposes:

```text
GET  state, overview, sources, settings, threads, tickets, models, prompts
POST triggers/:id/requeue, decisions/:id/dismiss
POST tickets/:id/retry, tickets/:id/stop, executor/pause
PUT  settings/:block, prompts, policy-sync
```

There is no endpoint to send an arbitrary user message or start a Ticket directly.
`GET threads/:key` returns incoming trigger/decision/ticket context; outgoing agent
replies are GitHub comments, not a thread-message API. `GET tickets/:id` exposes
assignment/report/attention metadata, not the full worker transcript.

The app can call this loopback API from its backend with `x-orchestrator-request: 1`
and Host `127.0.0.1:<port>`; browser direct calls are blocked by same-origin rules.

### Watchdog reality

- Health entries cover runtime, GitHub/Feishu sources, models, assessment, launches,
  delivery, relays, notices, replies, executor events and unavailable Evals
  (`src/infra/health.ts`, overview/source views).
- `scripts/dsh-superagent status` returns process/health/setup problems; the deployment
  guide recommends an hourly check in a separate DSH profile, with restart logic.
- Retry/attention/worker-slot/background-work lifecycle exists, but there is no
  autonomous "department is idle/spinning" watchdog that kills or reassigns work.
- The app still needs a supervisor for each profile: reachability, health, source poll
  errors, setup missing, queued/running load, tickets stuck in human stages, last
  activity, repeated failure, and restart policy. It should alert/notify, not silently
  kill.

## Can N superagents run in parallel?

**Yes at the process/profile level, with hard constraints:**

- Each instance is one DSH profile (`dsh --profile <name>`) in the `dsh-<profile>` tmux
  session. `scripts/dsh-superagent` keeps its control lock, service pid, logs and stop
  marker under `.artifacts/control/profiles/<profile>` and filters processes by
  `--profile`. Distinct profiles therefore do not block one another.
- Each profile needs its own `webserver.port`, `stateDir` and management URL. Reusing
  the default 3082 or one state directory for two profiles is not supported.
- One profile's worker pool, Tickets, worktrees and model concurrency are independent.
  N profiles multiply worker slots, model calls, disk use and GitHub API traffic; there
  is no cross-profile global worker cap in superagent.
- A shared GitHub agent account is technically plausible: each GitHub Source filters
  notifications by its configured repository and keeps its own cursor. It is not
  verified across profiles, and it multiplies notification polling/rate-limit use.
  Separate agent accounts per repo/profile are the safer default.
- `gh-agent` must be logged in as the agent account. The current wrapper is **not**
  logged in; the main `gh` session is a personal account and must not silently become
  the agent.
- The app must supervise each profile independently: reachability, health, setup,
  source poll errors, worker load, stuck Tickets and restart. One instance's failure
  must not take down the project room.

So parallel execution across repositories is viable; it is an **N-process deployment**,
not one superagent with N repo workers.

## Three information channels

The user's split is the right product boundary, but the current superagent does not
provide the third channel by itself.

### 1. Repository-internal channel — GitHub Issues/PRs

All implementation detail, worker reports, branch/PR discussion, CI and review stay in
the repository's Issues/PRs. Studio should store an external reference
(`repo`, issue/PR number, ticket ID) and show only a compact status/link. Do not copy
the full GitHub thread into the room; that would recreate the noise the split is meant
to remove.

### 2. Shared knowledge channel — project docs

A project-level docs folder or, for multi-repo/remote work, a dedicated docs
repository is the shared source of truth for cross-department facts, decisions,
contracts, glossary and links. Issue/comment bodies should reference the exact
file path or commit-pinned URL, never paste the document.

- A dedicated docs repo is more portable and auditable than a Studio-private folder.
- Superagent workers run with full local access, but the superagent Source only sees
  its own repository; the issue/comment must give the exact docs path/URL.
- Decide whether workers may write docs. Prefer a PR to the docs repo, or lead/app
  writes with worker proposals; do not grant broad push just to record notes.
- Studio can index the docs repo/folder and show it in the room, but the canonical
  content stays in the docs source.

### 3. Cross-department room channel — Studio room (web now, Feishu/WeChat later)

This is the gap. Superagent's Sources are GitHub and Feishu only. Its management API
has no arbitrary chat send/receive endpoint, and its worker sessions are not room
participants.

Options, in order of preference:

1. **Room MCP/DSH tool bridge (recommended for the web room).** Add a small DSH
   plugin/MCP server to each superagent profile exposing bounded
   `room_post`/`room_read` tools backed by Studio's authenticated room bridge. Only
   the lead/orchestrator preset gets the tools; workers do not. The room remains
   Studio-owned; superagent leads can participate without GitHub issue duplication.
   This needs a feasibility spike: confirm the superagent router preset can load an
   extra MCP client/tool and that tool calls are available in its main Session.
2. **Feishu-native room (later channel).** Superagent already supports a Feishu Source.
   A shared Feishu group could be the room, with one bot per profile and explicit
   mentions. The web room would bridge to Feishu. This is viable for the later
   WeChat/Feishu phase, but not a web-first implementation.
3. **GitHub issue relay (fallback).** Studio mirrors selected comments from a
   coordination issue per repo. This is asynchronous, duplicates coordination across
   repos and is not a true shared room. Use only as a temporary integration.
4. **A2A (not now).** Superagent has no A2A endpoint; A2A would require an adapter and
   does not replace the room bridge for the current web UI.

The room should carry only cross-department coordination, decisions, notifications and
links to docs/issues. Repo details and long evidence stay in channel 1 or 2.

## Proposed gateway architecture

```text
Department Studio project room
  ├─ Human chat (brief; no repo noise)
  ├─ Repo/superagent registry
  │    ├─ repo A → profile A (port, stateDir, agent account, local clone)
  │    ├─ repo B → profile B
  │    └─ ...
  ├─ GitHub issue gateway
  │    ├─ dispatch a task as an Issue (or comment) from an allowed account
  │    ├─ mention the agent account; include scope/acceptance/records links
  │    └─ mirror Issue/PR comments back into the room thread
  ├─ Superagent status proxy
  │    ├─ GET state/overview/sources/tickets/threads
  │    └─ health, load, setup problems, ticket stages
  └─ Supervisor/watchdog (notify-first)
       ├─ process/reachability + poll health
       ├─ stale ticket/activity and repeated failure detection
       └─ human/lead attention items; no automatic kill
```

### Repository/superagent registry

Project-scoped config (not credentials):

```text
repo id, owner/name, local clone, profile name, panel URL,
agent gh wrapper, state directory, allowed departments, default branch
```

One profile per repo; distinct ports/stateDirs; no shared worker pool. A shared
`gh-agent` account must be proven safe for multiple repositories; otherwise create one
agent account per repo/profile. The app should not assume a superagent can see a
different repo.

### Issue gateway

- A **dispatch** action, not every chat message, creates an issue/comment. The body
  contains the task scope, acceptance checks, repository/branch constraints, links to
  project records, and the exact superagent mention.
- The issue author/CLI must be on the superagent's allowed list or use an admitted
  explicit request; the mention must be in the initial issue/comment (editing a body
  to add it later is not received).
- The app uses a dedicated app GitHub identity, or the human's GitHub identity with
  explicit consent. Do not reuse the superagent's agent account for the app; it should
  be distinguishable for audit and policy.
- Chat display is fed by GitHub Issue/PR comments plus superagent ticket/health
  metadata. A direct reply in the room can create a new comment; this is asynchronous
  and eventually consistent. There is no token streaming.
- One issue per task. A project-level integration task that spans repos creates linked
  issues per repo and an app-level verification checklist; superagent has no
  cross-repo ticket dependency.

### Supervisor/watchdog

Poll each profile:

- `GET state` → runtime/setup/paused/health/load;
- `GET overview` → problems and attention;
- `GET sources` → poll errors/last cursor;
- `GET tickets?state=open` → stages, queued/running counts, stale human stages;
- optionally `scripts/dsh-superagent status`.

Raise one deduplicated attention item when: process unreachable, setup missing, poll
failures, no worker slot progress, a ticket waits on a person beyond its explicit
window, repeated identical failures, or no GitHub activity for a task while the
superagent is healthy. Prefer "inspect/retry/stop/reassign" actions; never auto-kill
solely on elapsed time. The superagent's own retry/worker-slot/background rules remain
the execution authority.

### A2A evaluation

A2A is not needed for GitHub-mediated repo superagents:

- GitHub Issues/PRs already carry task identity, comments, artifacts and review.
- A2A would add a second protocol for the same remote-work boundary, plus Agent Cards,
  auth, task/context mapping and conformance.
- Use A2A only if external, independently hosted agents must join the project room
  without a GitHub issue. In that case implement it as an external adapter, not as a
  replacement for superagent's local worker lifecycle.

## Validation experiments still needed

1. Log in `gh-agent` (or a dedicated agent account wrapper) and configure a
   **throwaway private test repository** in one superagent profile.
2. Enable `observeIssues`/comments as needed; add the app/test author to the allowed
   list; start the profile; verify `scripts status` and `GET state`.
3. Create a test Issue mentioning the agent, confirm a Ticket, worker run, GitHub
   comment and PR; measure polling/latency.
4. Read `GET threads`, `GET tickets`, and GitHub issue comments; verify the app can
   reconstruct the conversation without reading private DSH session files.
5. Create a second profile/port/stateDir for a second repo; test shared vs separate
   agent account and resource usage.
6. Test process restart, setup failure, source poll failure, stuck ticket and the
   proposed supervisor attention path.
7. Only then decide whether the Studio room should mirror issues as the primary
   conversation, or whether a direct chat API is required (not available today).

The current environment cannot complete these steps: `gh-agent` is not logged in, the
superagent profile has no repository configured and is not listening, and the local
sandbox blocks writing the profile's `.artifacts` control lock. No GitHub issue was
created during this validation.

## Recommendation

- **Prefer the superagent-per-repo gateway over rebuilding worker pools/watchdog in
  Studio**, provided the operational cost of N profiles/ports/state dirs and a room
  bridge is acceptable.
- Add the room MCP/DSH bridge before claiming the web room is the cross-department
  channel; GitHub comment mirroring alone is not real-time room chat.
- Build the gateway thin: repo registry, issue dispatch, read-only status proxy,
  GitHub comment mirror, supervisor attention. Do not reimplement superagent's
  Ticket/worker/retry internals.
- Keep the host-mediated worker design (`docs/worker-teams-design.md`) only as a
  fallback for runtimes/repos that cannot use dsh-superagent.
- Defer A2A until external/remote agents are required.
