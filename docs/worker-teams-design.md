# Department lead teams, workers, watchdog and multi-repository work

Status: **proposed architecture, not implemented.** This document responds to the
original product intent: each department lead talks to the human, decomposes accepted
work into small executable/verifiable tasks, and delegates them to workers. It also
evaluates the watchdog and A2A boundary against the local DSH superagent reference.

> **Updated direction (2026-11-22):** do not run one superagent per repo as the primary
> architecture. The preferred plan is the [hybrid reuse of selected superagent
> implementation](superagent-reuse-hybrid.md): keep the Studio room/leads/authority and
> port the Ticket/Assignment/Report, worker-slot/background, health/stage, GitHub
> issue/PR and worker-prompt patterns into the Python app. The host-mediated design
> below is the implementation shape; the one-repo-per-profile gateway is a fallback.

## 1. Why the live two-department demonstration failed

It did not fail in the room/worker design because that design was never exercised.
The bounded attempt stopped at the runtime prerequisites:

1. **Pi**: the direct smoke used the ambient `~/.pi/agent` directory, which is
   read-only in this environment (`EACCES` creating `settings.json.lock` and
   `auth.json.lock`). Pi never reached inference. Studio's generated per-run
   `PI_CODING_AGENT_DIR` avoids this path, but a full Studio run was not completed.
2. **DeepSeek Harness**: a writable copied `DSH_HOME` was prepared, but the
   `DEEPSEEK_API_KEY` in `~/.dsh/env-superagent.sh` was rejected with HTTP 401.
3. **Claude Code**: the one-word smoke did not finish within the 120-second
   verification window and was stopped. No result was accepted.

The real `live-demo` directory was backed up but **not migrated, restarted or
modified**. A copy of its v3 database migrated to v4 successfully (5 departments,
180 messages, 116 deliveries, 10 hierarchy edges). See `docs/verification.md` for the
record. The two-department live path therefore needs a valid key/writable config
before it can be judged.

## 2. Gap between the current implementation and the original intent

| Original intent | Current state | Gap |
|---|---|---|
| One lead per department talks to the human | Implemented: one persistent lead session per department | None for the lead layer |
| Lead decomposes accepted work | Not implemented: tasks are created by the human or by human task instructions | Need lead task tools and durable assignment records |
| Leads hand small tasks to workers | Not implemented: every delivery is a lead run; no worker process/session | Need a host-mediated worker pool |
| Workers are independently executable/verifiable | Not implemented | Need assignment scope, acceptance criteria, reports and verification evidence |
| Multiple GitHub repositories | Not implemented: each department has one workspace path | Need repository registry, worktrees, branches/PR/CI mapping |
| Per-department watchdog | Deferred: only a global 300-second delivery deadline and stop confirmation | Need phase-aware department/worker observation and attention, not auto-kill |
| A2A if needed | Deferred research only | Evaluate; do not conflate with local workers |
| Records/audit and short chat | Implemented | Good foundation; worker evidence should land here |
| Project isolation | Implemented | Workers must inherit project-scoped stores/sessions/records |

Current tasks (`backend/TASKS.md`) are durable **human-facing metadata** with an owner
lead and delivery links. They are not worker assignments: there is no worker process,
task report, acceptance check, dependency execution or watchdog. The new model should
extend this task surface rather than create a parallel task system.

## 3. Reference model: DSH superagent and agent-team

The local `dsh-superagent` prototype (and DSH's experimental agent-team packages)
separate:

- an **orchestrator/lead** that routes and assesses work;
- an **Executor/worker** that owns one Ticket/Assignment in its own session and
  directory;
- durable **Tickets, Assignments and Reports** (progress, waiting, ready, blocked,
  failed, dropped);
- a **worker-slot** budget and background-work rules;
- human **Attention** when a worker needs a decision;
- effects/outbox and confirmed shutdown/retry rather than fire-and-forget.

The key idea to reuse is **role and lifecycle separation**, not a central superagent.
Our product has several lead-orchestrators (one per department) inside one project
room. A central superagent above them is explicitly not wanted and would violate the
"no autonomous AI boss" constraint.

## 4. Proposed target model

### 4.1 Participant layers

- **Human**: project lead and final authority; addresses department leads in the room.
- **Department lead**: persistent agent session; talks to the human, decides when a
  request is clear enough, decomposes it, delegates, verifies and reports back.
- **Worker**: ephemeral agent session owned by one department and one task. It is
  **not** a room participant, has no handle, cannot be @mentioned and cannot post in
  the room. Its result goes to its lead and to project records.
- **Host**: Studio core. It owns identity, task records, worker process lifecycle,
  permissions, budgets, watchdog observations and audit.

### 4.2 Lead/worker tools

Lead-facing bridge tools (names illustrative; Pi extension + MCP share the contract):

```text
team_plan_task(parent_task_id?, title, scope, acceptance, repo?, deps?, worker_budget?)
team_merge_task(task_id, revision, ...)
team_spawn_worker(task_id, title, scope, acceptance, repo?, model?, permission?)
team_send_worker(worker_id, text)
team_list_team()
team_worker_status(worker_id)
team_wait_worker(worker_id, timeout_ms)   # bounded observation, not sleep-polling
team_cancel_worker(worker_id)
team_report_task(task_id, report, evidence, record_path?)
team_publish_lead_update(text, record_path?)
```

Workers get a smaller tool surface:

```text
worker_read_context(record_path)
worker_write_record(name, content, append|replace)
worker_report_progress(summary)
worker_report_ready(evidence, record_path)
worker_report_blocked(reason)
worker_report_failed(reason)
```

Workers may use the runtime's file/shell tools only when the lead/task is Develop;
Discuss workers are read-only. Workers cannot spawn further workers by default
(depth 1), matching DSH's bounded delegation. A task's `permission` can only narrow
the lead's permission, never widen it.

### 4.3 Task/assignment lifecycle

Extend the existing `tasks` table rather than replacing it:

- Task: stable ID, project ID/scope, parent ID, owner lead, title, scope, context,
  acceptance/verification criteria, repository/worktree reference, permission,
  priority, dependencies, lifecycle open/closed, revision.
- Assignment: one worker run for a task; worker ID, runtime/model, workspace,
  native session reference, generation, state, deadline/heartbeat, report.
- Report: `progress`, `waiting`, `ready`, `blocked`, `failed`, `dropped`; bounded
  summary, record path, verification commands/results, changed files/PR links.
- Attention: a question that needs a human or lead decision; deduplicated and
  resolved explicitly, so it does not become routine Activity spam.

Suggested states:

```text
task:       open -> in_progress -> ready_for_review -> verified | closed
                       | blocked | failed | canceled
assignment: queued -> starting -> running -> waiting
                    -> completed | failed | interrupted | canceled
report:     progress | waiting | ready | blocked | failed | dropped
```

A worker completion must never be treated as task completion. The lead reviews the
report and evidence, then verifies or retries. The human sees only compact status and
explicit attention items; detail belongs in records.

### 4.4 Lead wake-up after worker completion

Workers are asynchronous. When a worker reports `ready`, `blocked` or `failed`, the
host should wake the owning lead with a bounded internal event (not a public room
message), unless the lead is already active. To avoid loops:

- at most one automatic wake per assignment completion;
- a per-department wake budget/window;
- no automatic wake for `progress` reports;
- room messages only when the lead decides the human needs a decision/result;
- a worker that dies without a report produces one attention item, not repeated loops.

The first increment may use an explicit `team_wait_worker` bounded wait for a simple
synchronous workflow, but the target path is automatic wake with a budget. This is an
open decision because it changes scheduling semantics.

### 4.5 Concurrency and isolation

- Per-department worker slots (default 2–3), global worker cap, project cap.
- Each Develop worker gets its own git worktree/branch under the project data
  directory, not the lead's workspace. Discuss workers may share a read-only checkout.
- Every worker gets a distinct native session (`worker-<id>`), no room identity.
- Stop/cancel: revoke the worker generation, close stdin, confirm process exit, then
  report; never kill unrelated lead/peer work.
- Restart: resume or fail assignments explicitly; no silent replay of shell/model
  work. Reports remain durable.

## 5. Watchdog: per department, phase-aware, notify-first

Current 300 seconds total is a delivery deadline, not a progress watchdog. Workers can
legitimately run long builds or wait for CI, so a fixed wall-clock kill is wrong.

Watchdog inputs (bounded, sanitized):

- lead status: idle/running/waiting, last delivery generation;
- open tasks and their dependencies;
- assignment state and last **observable** progress timestamp;
- worker process alive/exit confirmation;
- report state and wake-up delivery status;
- repeated identical failure/retry counts;
- optional file/record/PR/CI observations where available.

Signals to classify:

1. **Healthy**: active process or a known long operation; no attention.
2. **Expected waiting**: waiting for human, CI, dependency, or a bounded external
   operation; no attention until the expected window passes.
3. **Suspected stall**: no progress and no explicit waiting state for a phase-aware
   window, repeated observations.
4. **Dead/exited without report**: process exit with queued task; attention.
5. **Department idle with work**: open ready tasks but no active worker/wake-up.
6. **Dependency deadlock**: all tasks blocked on each other.
7. **Spin**: repeated identical failure/retry or lead/worker loop beyond a threshold.

Policy:

- Do **not** auto-kill solely on elapsed time.
- Create one deduplicated attention item with safe evidence and choices: keep waiting,
  inspect, retry, stop, reassign.
- Resolve/retract when progress resumes; atomically record resolution.
- Separate hard limits (max run time, max retries, max tokens) are explicit config and
  must be labeled as hard resource limits, not health detection.
- Preserve human Pause/stop and confirmed-exit behavior.
- Watchdog itself must be restart-safe and must not become an autonomous lead.

The DSH superagent reference provides lifecycle/stall-free stages, worker slots,
background-job limits, retry/handoff and explicit Attention, but not a generic
wall-clock watchdog; we should adopt its state discipline rather than copy a timer.

## 6. Multiple GitHub repositories

This is phase C, after single-repo workers are proven.

Proposed project-scoped repository registry:

```toml
[[repositories]]
id = "frontend"
path = "/work/app-frontend"
remote = "github.com/org/app-frontend"
default_branch = "main"
credential_ref = "GITHUB_TOKEN"   # name, never the value
```

- A department may be allowed a subset of repositories. A task chooses one repo or an
  explicit multi-repo set; workers cannot escape their allowed set.
- Worktree manager creates `worktrees/<task-id>/<repo>` from the repository checkout;
  one branch naming convention per task; cleanup/retention is explicit.
- Worker tools: `git`/`gh` plus verification commands; push and PR creation require
  explicit task permission and human authorization policy. No auto-merge.
- Cross-repo tasks have dependencies and an integration/verification task. A lead
  can only report `ready` when each repo's checks/PR links and the combined verification
  evidence are recorded.
- Credentials come from environment/`gh auth`/a credential reference; never enter
  prompts, records or git config written into the repo.
- The workspace path is still not an OS sandbox; repository allowlists and branch
  naming reduce accidental cross-repo damage, not malicious processes.
- GitHub webhooks/PR review/CI ingestion can come later as Sources; first increment
  can use explicit `gh` commands and polling.

## 7. A2A evaluation

A2A is for **interoperability with independently hosted agent services**, not for
launching local workers. It defines Agent Cards, messages, tasks, contexts, status,
artifacts, cancellation and auth bindings. It does not supply:

- a local worker process/session lifecycle;
- room membership or multi-lead identity;
- a task board/watchdog for local departments;
- GitHub repository orchestration.

It is useful later if departments can be hosted in another process, machine or
organization, or if external agents must delegate work into Department Studio.

Recommendation:

1. **Do not implement A2A now.** Local workers/watchdog/multi-repo are higher value
   and A2A adds protocol/auth/lifecycle mapping without replacing them.
2. Keep the runtime-neutral `AgentBackend` boundary; add an `A2aBackend` later that
   maps A2A Task/context/cancel to a remote Agent Card endpoint.
3. Expose an A2A server/Agent Card only after auth, discovery, idempotency,
   input-required mapping, cancellation and restart recovery are designed and tested.
4. Do not claim A2A conformance. The current research doc cites v1.0.1 wire version
   1.0; the SDK/protocol versions are distinct and were not exercised.
5. Re-evaluate if the user wants external departments/remote workers, not merely
   multiple local GitHub repos.

## 8. Proposed increments (TDD)

### Phase A — lead-to-worker delegation (single repo, one project)

- Schema v5: task extensions, assignments, worker reports, attention; migration from
  v4 with no data loss.
- WorkerPool per project/department; runtime registry reuse; model/worker settings.
- Lead bridge tools; worker minimal tools; records evidence; compact team panel.
- Tests: task decomposition limits, permission inheritance/narrowing, concurrency,
  worktree isolation, report lifecycle, no room identity for workers, cancellation,
  restart/no replay, record links, UI.
- No multi-repo, no A2A, no auto-kill watchdog yet.

### Phase B — watchdog

- Observation store and phase-aware classifier; deduplicated attention; wake-up
  budgets; restart recovery.
- Tests: healthy long work, silent tool, provider wait, dead process, orphan assignment,
  dependency deadlock, retry spin, false-positive suppression, Pause/stop race.
- Notify-first; no automatic kill or permission change.

### Phase C — multiple repositories / GitHub

- Repository registry, allowlists, worktrees, branch/PR/CI mapping, integration tasks.
- Tests: repo isolation, worktree cleanup, credential non-leakage, PR/check evidence,
  cross-repo dependency and verification, no auto-merge.
- Human approval gates for push/PR/merge.

### Phase D — A2A (only if external agents are required)

- Agent Card/discovery, auth, task/context mapping, cancellation, idempotency,
  restart/recovery; conformance tests; no claim before verification.

## 9. Decisions needed before coding

1. **Worker model/runtime**: inherit each lead's runtime/model, or a separate
   `worker_model` per department (recommended: separate worker config, default to a
   cheaper model, with explicit capability/route checks)?
2. **Worker workspace**: per-task worktree (recommended) or shared lead workspace?
3. **Lead wake-up**: automatic bounded wake on worker completion (recommended), or
   only on the next human message for the first increment?
4. **Depth**: workers cannot spawn workers by default (recommended); allow one
   bounded sub-worker depth only if explicitly requested?
5. **GitHub**: which repos/account, `gh` auth source, and whether leads may push/open
   PRs without a human approval step. Recommendation: prepare branches/PRs but require
   human approval for push/merge; never auto-merge.
6. **Watchdog**: notify-only with explicit retry/stop (recommended), or an automatic
   hard timeout? Recommendation: no automatic kill; configure separate hard caps only
   after review.
7. **A2A**: defer until external/remote agents are a real requirement (recommended),
   or design the A2A server/client in this increment?
8. **Worker budget**: per department slots, global slots, task/attempt limits, and
   whether worker completion may wake a lead without a human request.

## 10. Relationship to existing code

- Reuse `RuntimeRegistry` and the three adapters for worker processes; add a worker
  request context instead of creating another agent abstraction.
- Reuse project-scoped Stores, records, hierarchy, tasks, delivery generation and
  confirmed-stop logic.
- Keep workers out of `leads` and room messages; they are not departments.
- Keep the human as final authority; worker delegation never broadens permissions.
- Keep chat brief: worker detail goes to records; the lead reports only decisions,
  blockers and outcomes.

No code is changed by this proposal. The next step is deciding the open questions and
then planning Phase A with schema/wire contracts and failing tests first.
