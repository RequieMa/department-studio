# Hybrid: reuse selected dsh-superagent implementation in Department Studio

Status: **proposed, not implemented.** This supersedes the "run one superagent per
repository as the primary architecture" recommendation. The gateway remains a
fallback, not the product plan.

## Why this direction

The current Department Studio already has the valuable human-facing layer:

- one room with multiple department leads and stable identities;
- human authority, hierarchy and default addressing;
- project isolation, records and audit;
- runtime-neutral Pi/Claude Code/DeepSeek Harness adapters;
- a browser room without a separate build step.

The local `dsh-superagent` has the valuable repository execution layer:

- Ticket / Assignment / Report lifecycle and explicit stages;
- worker sessions with worker slots, background-work rules and confirmed stop;
- retry, attention and handoff rules;
- health/status surfaces;
- GitHub issue/PR/CI polling, idempotent comments and issue-driven work;
- worker/orchestrator prompt separation;
- a permission/authority discipline around who may start work and what a Ticket
  allows.

We should **port the selected contracts and algorithms into Studio**, not run
superagent as a black-box service and not rebuild everything from scratch.

Direct code import is not literal across TypeScript and Python. "Reuse" means:

1. port the state machine, data shape and rules with tests;
2. reuse the GitHub/worktree/worker patterns, not the DSH profile/panel;
3. attribute the source module and keep behaviour differences explicit.

A TypeScript sidecar could import the original code, but it adds a second runtime,
DSH profile lifecycle, IPC, auth and deployment surface. That is not the right first
Web demo. The gateway/one-superagent-per-repo approach remains an option if we later
choose to delegate whole repositories to existing superagent instances.

## Product flow

```text
Human ↔ Studio room ↔ Department leads
                         │
                         │ 1. discuss, agree scope
                         │ 2. create a TASK PROPOSAL (no external side effect)
                         │ 3. human/owner confirms dispatch
                         ▼
                 Task records + optional GitHub issue
                 (repo, owner department, scope, acceptance, deps)
                         │
                         ▼
              Department lead → worker pool → repo worktree
                         │
                         ├─ repo detail/PR/CI → GitHub issue/PR only
                         ├─ evidence/summary → project records
                         └─ progress/blocker → lead → short room message
```

### Not every chat becomes an issue

Chat is for negotiation and coordination. A task issue is created only after a lead
has a concrete allocation and initial design. The proposal contains:

- target repository and owner department;
- objective and non-goals;
- scope/files/contracts that may change;
- acceptance and verification commands;
- dependencies and expected worker budget;
- links to shared records/docs (exact paths, not pasted documents);
- whether push/PR creation is authorized, or human approval is required.

Default gate: **the lead proposes; the human confirms dispatch**. A project may later
enable auto-dispatch for explicitly trusted repos/permissions, but not by default.

The issue body is the execution contract, not the discussion transcript. The room
shows a compact task card: owner, repo, issue link, stage, blockers and a records link.

### Issue assignment to a department

GitHub assignees are users, not departments. Studio owns the department mapping:

- issue label `studio:<department-id>` or the configured department label;
- assignee = the department's agent account (if it has one) or the project
  orchestration account;
- Studio records `owner_lead_id`, `repo_id`, `issue_number`, `task_id`;
- a single project account may create the issue, but the task owner remains the
  department; the issue body names the owner and the agent account.

Do not infer department ownership from GitHub labels alone; the Studio record is
authoritative.

## What to reuse from dsh-superagent

| Source | Reuse | Adaptation |
|---|---|---|
| `src/core/model.ts` Ticket/Assignment/Report/Attention | Data shape and invariants | Subset; IDs scoped to Studio project/department |
| `src/core/stage.ts` | Stage classification and retry eligibility | Add Studio delivery/worker states; tests copied as behaviour cases |
| `src/core/tickets.ts` | Assignment lifecycle/report rules | Port transactionally into SQLite |
| `src/executor/background.ts` | Background jobs, quiet detection, bounded kill/stop | Use Studio worker process/process-group APIs instead of DSH `ctx.jobs/subagents` |
| `src/executor/dsh.ts` | One worker Session/directory per Ticket | Use `AgentBackend` with per-worker session/ref |
| `src/infra/health.ts` | Health entries and single-writer registry | Department/worker health board |
| `src/app/retry-health.ts` | Observable budget/retry status | Keep bounded, sanitized status only |
| `src/sources/github.ts` / `github-read.ts` | Issue/PR/comment/CI mapping, idempotency, PR binding | Python `gh`/REST client; poll only what the project needs |
| `prompts/worker.md`, `prompts/dispatch.md` | Lead vs worker boundary and issue-scoped prompt | Combine with Studio instructions/records/room rules |
| `src/app/views/tickets.ts` | Compact stage/attention/worker-slot view | Web room task/team panel |
| `scripts/dsh-superagent status` hourly check | Supervisor shape | Studio supervisor for its own workers/repos |

### Do not port

- the one-repository-per-profile deployment and DSH web panel;
- full Source/Eval/Policy machinery for every GitHub event; Studio already owns
  human authority and room policy. Add only the GitHub intake needed for tasks;
- superagent's Feishu channel; Web room first;
- DSH session/agent internals; Studio's runtime adapters remain the execution
  boundary.

## Worker model

- A worker is an ephemeral agent session owned by one task/department. It is not a
  room participant, has no handle and cannot be @mentioned.
- Workers receive a bounded prompt built from the task issue/record, repo, acceptance
  criteria, allowed tools and permission. They do not read the whole room transcript.
- Each Develop worker gets a per-task git worktree/branch under project data; Discuss
  workers may use a read-only checkout.
- Worker slots per department and project; global cap; queue when full.
- Workers report `progress`, `waiting`, `ready`, `blocked`, `failed`; only `ready`
  enters lead review. Worker completion is not task completion.
- Lead verifies evidence, can request changes/retry, then marks task verified.
- Worker result detail goes to records/issue; room only gets a short lead update.

## Information channels

1. **Repo-internal:** GitHub issue/PR comments, CI, review. Studio stores references
   and mirrors only compact status.
2. **Shared knowledge:** project docs repo/folder. Issue bodies include exact paths or
   commit-pinned URLs. Prefer docs PRs for changes; no long documents in the room.
3. **Room:** cross-department coordination, decisions and notifications. Studio-
   owned message bus; Web first, Feishu later, WeChat/Enterprise WeChat adapter only
   after a bot-capable API is chosen. Department leads can participate; workers do
   not.

For the current Python Web app, the lead uses existing bridge tools plus new task
tools. No extra DSH MCP room bridge is needed for workers because they are host-managed
and report internally.

## Watchdog

Port the **stage/health/slot** discipline, not a wall-clock killer:

- observe worker process liveness, last progress/report, queued/running slot, repo
  worktree, GitHub issue/PR/CI state, lead wake-up delivery;
- classify healthy, expected waiting, suspected stall, dead/exited without report,
  department idle with ready work, dependency deadlock and retry spin;
- create one deduplicated attention item with inspect/retry/stop/reassign choices;
- never auto-kill or change permission on elapsed time alone;
- hard caps (max runtime, attempts, tokens) are separate explicit configuration;
- restart preserves records and marks interrupted work; no silent replay.

## Multi-repository

- Add a project repo registry: id, local clone, remote, default branch, credential
  reference, allowed departments.
- A task is scoped to one repo, or an explicit multi-repo set with dependencies and a
  final integration/verification task.
- Worktree manager per task/repo; branch naming; PR/CI binding; no auto-merge.
- Cross-repo integration belongs to the project/lead, not one worker; the lead may
  create linked issues per repo and a project-level verification task.
- Credentials from env/`gh auth`/secret refs; never prompt/records/git config.

## A2A

Not needed for the Web demo. GitHub issues + the Studio room cover the execution and
coordination boundaries. A2A is a later external-agent interoperability adapter; do
not block the worker/team work on it.

## Web demo scope

1. One project, two departments, one or two repos.
2. Department leads negotiate in the room; one lead creates a task proposal; human
   confirms; Studio creates one GitHub issue in the target repo.
3. The owning lead spawns one worker in a worktree; worker reports; lead verifies;
   room shows compact task/stage and a records link.
4. GitHub issue/PR comments are linked, not pasted; shared docs are referenced by
   exact path/URL.
5. Supervisor/watchdog shows health/attention for the worker and task.
6. No Feishu/WeChat/A2A in the first demo.

## TDD phases

1. **Domain/schema:** port Ticket/Assignment/Report/stage rules and tests to Python;
   schema v5 migration from v4; no UI.
2. **Worker core:** worker registry/slots, worktree isolation, prompt builder, report
   lifecycle, stop/restart/no replay; fake backend fixtures.
3. **Task proposal → issue:** lead bridge tools, human approval gate, GitHub fake
   issue/comment client, idempotency, records links; repository/stage UI.
4. **Watchdog:** phase-aware observation, attention, retry/stop; tests for healthy
   long work, dead process, orphan assignment, deadlock, spin and restart.
5. **Web demo:** two departments, one repo, end-to-end synthetic plus a user-approved
   live issue.
6. **Later:** multi-repo worktrees/PR/CI, Feishu channel, A2A evaluation.

## Open decisions

1. Port selected modules to Python (recommended) vs a TypeScript sidecar importing
   superagent code.
2. Task issue creation: human confirmation by default (recommended) vs lead
   auto-dispatch per repo/project setting.
3. Worker model: per-department worker model config vs inherit lead model.
4. Worktree layout/root and retention.
5. GitHub identity for issue creation: project orchestration account vs each
   department's agent account.
6. Which repo(s) and agent account are safe for the first live demo.
7. A2A: keep deferred.

No code is changed by this proposal. The first implementation step should be Phase 1
with failing tests and a schema design reviewed before migration.
