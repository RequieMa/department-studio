# Known issues and current limitations

Status baseline: **2026-11-22**, commit `d5b2856` (CLI project-manager fix and external
usage guide). This is a working issue register, not a roadmap promise. Each item states
what is actually implemented now, how to verify it, and what would close it. Design
documents are not evidence that a feature exists.

Use this file while trying the app from another project. Add a dated note under an
item when your observation changes; move the item to **Resolved** only after the
behavior and regression test exist.

## Status legend

| Status | Meaning |
|---|---|
| **Open** | Confirmed gap in the current implementation |
| **Blocked** | Implementation exists but a live prerequisite is unavailable |
| **Deferred** | Explicitly out of the current increment; not a regression |
| **Fixed** | Reproduced, corrected and covered by a test |

## Summary

| ID | Area | Status | Severity |
|---|---|---|---|
| KI-01 | Worker execution / worker sessions | Open | High |
| KI-02 | Lead task proposal → human permission → GitHub issue | Open | High |
| KI-03 | Worker reports, acceptance, team task lifecycle | Open | High |
| KI-04 | Live model verification for Pi/Claude/DeepSeek | Blocked | High |
| KI-05 | GitHub agent identity/repository for execution | Open | High |
| KI-06 | Web worker/issue/team status surface | Open | Medium |
| KI-07 | Worker model is configuration-only | Open | Medium |
| KI-08 | Multi-repository, worktree, PR/CI orchestration | Open | Medium |
| KI-09 | Watchdog / idle-spin detection | Deferred | High for long work |
| KI-10 | “No objection” approval semantics and persistence | Open | High |
| KI-11 | Shared docs channel is design-only | Open | Medium |
| KI-12 | A2A and superagent gateway | Deferred | Low/Medium |
| KI-13 | Human record edit/append UI | Open | Low |
| KI-14 | Project deletion uses native confirm | Open | Low |
| KI-15 | Live-demo production data is still v3 / unmigrated | Blocked operational | Medium |
| KI-16 | `gh-agent` credential storage and repo scope | Open operational | Low/Medium |
| KI-17 | Validation instance in `/tmp` and no model turn | Known limitation | Low |
| KI-18 | No worker budgets/slots/retry policy yet | Open | Future |

---

## KI-01 — Worker execution is not implemented

**Status:** Open. **Severity:** High.

**Actual now:** Departments have a lead model and an optional worker model, but there
is no worker process, worker session, worker queue, worktree or tool policy. Every
agent run is still a lead delivery. The adapter code has Discuss/lead behavior only;
the development-tool path for workers does not exist.

**Verify:**

- In the department dialog, selecting a worker model saves it but no “spawn worker”
  action exists.
- Search source for worker execution: `worker_provider`/`worker_model_id` occur only
  in settings validation/store/API/UI; there is no worker runtime class.
- The room and task panel show human/lead activity, not worker activity.

**Closes when:** a worker can be scheduled for a task, runs in an isolated worktree or
read-only checkout, reports progress/result, is cancellable, and has tests for
permission/isolation/stop/restart. This is Phase A in
[superagent-reuse-hybrid](superagent-reuse-hybrid.md).

## KI-02 — Task proposal, human permission and GitHub issue creation are not implemented

**Status:** Open. **Severity:** High.

**Actual now:** The UI has project/room/records/hierarchy/task-metadata surfaces. It
does not have a “create task proposal”, “ask the human for permission”, or “create
GitHub issue” flow. The task panel is human-created task metadata, not the planned
lead proposal → permission → issue workflow.

**Verify:** send a room message asking a lead to create an issue; there is no tool or
API for issue creation. `gh-agent` login does not create issue support in the app.
Check `/api/tasks` — it manages task metadata, not GitHub issues.

**Closes when:** a lead can create a task proposal, the room records the human’s
permission/objection, an idempotent issue is created only after approval, and the task
links to repo/issue/records. See KI-10 for the approval ambiguity.

## KI-03 — Worker report, acceptance and team task lifecycle are absent

**Status:** Open. **Severity:** High.

**Actual now:** There is no Assignment/Report state, no worker evidence/acceptance,
no worker-slot queue and no automatic lead wake-up. The current task panel can show
owner/instruction history, but it does not represent a running worker or a report.

**Verify:** no worker report endpoint or UI; no assignment table beyond lead
deliveries; task states are not wired to worker execution.

**Closes when:** a ported Ticket/Assignment/Report lifecycle is durable, workers can
report progress/waiting/ready/blocked/failed, lead acceptance is explicit, and
restart/cancel are tested. Source concepts:
`dsh-superagent/src/core/stage.ts`, `tickets.ts`, `executor/background.ts`.

## KI-04 — Live model-backed collaboration has not been established

**Status:** Blocked. **Severity:** High.

**Actual now:** Adapters are fixture-tested. A bounded attempt on 2026-11-21 was
blocked by:

- Pi: default `~/.pi/agent` was read-only (`EACCES` creating lock files);
- DeepSeek Harness: configured key returned HTTP 401;
- Claude Code: one-word smoke did not finish in the 120-second window.

No successful live model turn, peer message, cancellation or restart/resume is
claimed. The external-project validation created a project/department/message with no
model call.

**Verify:** use a valid runtime/key and make a one-word Discuss reply in a throwaway
project; check the returned model and the room bridge. Do not run a large conversation
before the smoke passes.

**Closes when:** each supported runtime has a documented live smoke (runtime, model,
bridge, stop/restart behavior) with sanitized evidence. See
[verification](verification.md) and [live demo](live-demo.md).

## KI-05 — GitHub agent login exists, but execution repo/identity is not configured

**Status:** Open. **Severity:** High for issue-based execution.

**Actual now:** `gh-agent` is logged in as `RequieMa-Agent` with `repo`, `read:org`,
`gist`, `workflow`. It sees one repository:

```text
RequieMa-Agent/dual-faced-world-w12-evidence   (public, ADMIN)
```

No superagent profile has a repository configured, no panel is listening, and no
issue has been created. The account email is not visible through the GitHub API; the
login was completed by the user as the intended agent account.

**Verify:**

```bash
GH_CONFIG_DIR="$HOME/.config/gh-agent" gh auth status
GH_CONFIG_DIR="$HOME/.config/gh-agent" gh repo list --limit 20
```

**Closes when:** a **private throwaway test repo** is explicitly approved, the agent
account has the required access, and the app can create a test issue without using a
personal account. Do not use the public evidence repo by default.

## KI-06 — Web has no worker/issue/team status surface

**Status:** Open. **Severity:** Medium.

**Actual now:** The Web room shows project, departments, messages, room state,
records, hierarchy, task metadata and theme. It does not show a worker/issue dashboard,
worker slots, active assignments, reports, GitHub PR/CI state or cross-repo status.
The current `External validation` screenshot is in
[getting-started](getting-started.md#5-see-chat-status-in-the-web-ui).

**Verify:** open the room; there is no worker/issue section. Do not infer worker
status from the task metadata panel.

**Closes when:** the Web exposes compact task/worker/issue state and links, while
keeping long evidence in records/issues.

## KI-07 — Worker model is configuration-only

**Status:** Open. **Severity:** Medium.

**Actual now:** The department dialog stores `worker_provider`/`worker_model_id` and
defaults to the lead model. No worker ever uses it. Existing leads have empty worker
fields until edited; legacy `permission: develop` is ignored and loads as Discuss.

**Verify:** save a worker model, inspect the lead JSON/DB; no worker process or
delivery uses it. The dialog text explicitly says worker execution is preparatory.

**Closes when:** KI-01 exists and a worker run resolves this model, with catalog/
credential/availability checks and a test that it does not silently fall back to the
lead model.

## KI-08 — Multi-repository, worktree, PR and CI orchestration are absent

**Status:** Open. **Severity:** Medium.

**Actual now:** Each department has one local `workspace` path. There is no project
repository registry, per-task git worktree, branch/PR binding, CI polling or
cross-repo dependency graph. The selected workspace is not a sandbox and Studio does
not clone repositories.

**Verify:** the department dialog has one workspace field; no repo registry/worktree
UI or API. `git worktree` behavior is not part of Studio.

**Closes when:** a project can register repos/allowlists, a task can select a repo or
explicit multi-repo set, workers get isolated worktrees, PR/CI evidence is linked, and
cross-repo integration has a verification path. No auto-merge.

## KI-09 — Watchdog / idle-spin detection is deferred

**Status:** Deferred. **Severity:** High for long worker runs.

**Actual now:** The room still has a **300-second delivery deadline** and explicit
pause/stop. There is no per-department watchdog, heartbeat/progress classifier,
attention item or automatic retry/reassign. The current task metadata is not a
worker-health signal.

**Verify:** read `docs/watchdog-follow-up.md`; no watchdog process/table/API exists.
Long model work is still bounded by the delivery deadline.

**Closes when:** a phase-aware, notify-first watchdog observes workers/tasks,
deduplicates attention, handles restart/dead process/deadlock/spin, and has tests for
healthy long work and false-positive suppression. Do not auto-kill solely on elapsed
time.

## KI-10 — “No objection” approval semantics are not implemented

**Status:** Open. **Severity:** High.

**Actual now:** The written flow says the lead asks the human in the room; if the
human replies without objection/approves, the lead may create the issue. If the human
objects or does not answer, nothing is created. There is no room proposal record, no
approval state, no timeout and no issue tool.

The wording is deliberately conservative: **no reply means no creation**, not
“silence equals consent”. If you want a timeout-based rule, it needs an explicit
duration and a decision record; it is not implemented.

**Verify:** no approval UI/API/table; task issues cannot be created.

**Closes when:** the room stores a proposal and the human response, the lead can
create exactly one issue only after approval, and objections/no-response are tested.
If timeout approval is desired, specify the window and audit behavior first.

## KI-11 — Shared docs channel is design-only

**Status:** Open. **Severity:** Medium.

**Actual now:** Project records exist and are the closest implemented shared
knowledge channel. The planned dedicated docs repo/folder with issue/room references,
commit-pinned URLs and docs PR policy is not implemented. Superagent workers do not
exist, so they cannot yet read/write shared docs through a task issue.

**Verify:** Records UI works per project; there is no docs-repo registry or docs PR
workflow.

**Closes when:** the project has a shared docs source of truth, tasks/issues reference
exact paths/URLs, access/write policy is explicit, and the room/records UI can point
to it without pasting documents.

## KI-12 — A2A and the superagent-per-repo gateway are deferred

**Status:** Deferred. **Severity:** Low/Medium.

**Actual now:** No A2A Agent Card/server/client, no A2A conformance claim. The
one-superagent-per-repo gateway was validated as a fallback design only; no profile
is configured and no issue flow runs. The preferred plan is selective reuse of
superagent implementation in Python ([hybrid design](superagent-reuse-hybrid.md)).

**Verify:** no A2A code/endpoints; no running superagent panel at 3082; no repo
configured in the superagent state DB.

**Closes when:** external/remote agents become a real requirement and an A2A adapter
passes auth/task/context/cancel/idempotency tests, or a repo-gateway spike is approved.

## KI-13 — Human record edit/append UI is incomplete

**Status:** Open. **Severity:** Low.

**Actual now:** The API supports `POST /api/records` (create) and
`PUT /api/records/{name}` with `append`/`replace`; the Web UI currently supports
creating and viewing records, not editing/appending an existing record. Agents can
append through the bridge. Record names are flat `.md`, content is capped at 512 KiB.

**Verify:** create a record in the UI, then inspect the UI for an edit/append action;
the API is available but no form is exposed.

**Closes when:** the Web exposes a deliberate append/replace control with revision or
audit semantics, and tests cover owner/runtime access and bounded content.

## KI-14 — Project deletion uses a native confirm, not typed-name confirmation

**Status:** Open. **Severity:** Low.

**Actual now:** The project API requires `?confirm_name=<exact name>`; the browser
uses a native confirmation that supplies the active project name automatically. It is
not the same deliberate typed-name experience as department deletion.

**Verify:** delete an inactive project in the UI; observe the native confirm.

**Closes when:** the project dialog asks the user to type the name and sends the exact
value, with stale/active/error cases tested.

## KI-15 — Live-demo production data is still v3 and was not migrated

**Status:** Blocked operational. **Severity:** Medium.

**Actual now:** The real `live-demo` directory was backed up but not migrated,
restarted or modified. It remains schema v3 with legacy qgenie provider/model values
in its departments. A v3 copy migrated to v4 cleanly (5 departments, 180 messages,
116 deliveries, 10 edges); the original still needs a human-controlled backup and
relaunch, and its old models need replacement before it can run.

**Verify:** inspect the original `live-demo/room.sqlite`; do not open it with a writer
casually. Backup:
`artifacts/live-demo-pre-live-2026-11-21-232350/` (git-ignored, SHA256SUMS).

**Closes when:** the human decides to upgrade/relaunch; stop writers, back up, use the
same absolute data dir, then replace stale models. Do not downgrade.

## KI-16 — `gh-agent` credential storage and repo scope are operational risks

**Status:** Open operational. **Severity:** Low/Medium.

**Actual now:** `gh auth login` stored the token under
`~/.config/gh-agent/hosts.yml` with mode `0600` (plaintext fallback). The agent account
currently sees one public repo. There is no separate OS account/container for
superagent/worker execution; worker isolation is not implemented.

**Verify:** inspect file mode (not contents), `gh auth status`, repo list. Never paste
the token into chat/records.

**Closes when:** decide whether to use a keyring/secure storage, which account per
repo, and what OS-level isolation is required before enabling development workers.

## KI-17 — External validation is ephemeral and has no model turn

**Status:** Known limitation. **Severity:** Low.

**Actual now:** The validation instance used:

```text
/tmp/studio-external-demo
/tmp/studio-external-data
project: External validation
department: External Validator / @validator
```

It created a second project, a lead with worker-model config, and a paused-room
message. The screenshot is `docs/assets/external-validation-room.png`. No model
call, worker, issue, Feishu/WeChat or A2A path was exercised. `/tmp` is disposable.

**Verify:** [getting-started](getting-started.md#9-current-validation-snapshot).

**Closes when:** a durable external project (outside this checkout) completes the
same flow plus a real Discuss smoke and, later, the worker flow. Use your own paths
and do not commit tokens.

## KI-18 — No worker budgets, slots, retry policy or cross-repo integration yet

**Status:** Open. **Severity:** Future.

**Actual now:** Existing limits are for lead deliveries (eight deliveries per human
chain, two active leads, one delivery per lead, five-minute deadline). There are no
per-department worker slots, queue, attempt limit, token budget, retry policy or
cross-repo verification budget.

**Verify:** no worker scheduler exists (see KI-01/KI-03); only room delivery limits
are active.

**Closes when:** worker scheduling has explicit project/department/global caps,
queueing, retry/backoff, cancellation and tests for exhaustion/restart.

---

## Resolved during external validation

### CLI injected an embedded project and blocked new-project creation

**Status:** Fixed in `d5b2856`.

**Symptom:** a real CLI launch created an **embedded** project; `POST /api/projects`
returned `409 Project creation is unavailable in this embedded session`, even though
the UI showed Project history/New project.

**Cause:** `cli.py` passed `store=store` to `create_app`, selecting
`EmbeddedProjectManager` instead of `ProjectManager`.

**Fix:** bind the port first, call `create_app(settings)` without an injected Store,
and let the app open the project catalog/active project. A wheel-level regression test
now creates a second project through the real CLI.

**Verification:** external instance at `/tmp/studio-external-data` created
`External validation`; the screenshot is in [getting-started](getting-started.md).

## Clarifications that are not bugs

- The Records button showing **1** on a fresh project is the bundled
  `records/README.md`, not a phantom user record.
- A message sent while paused appears in the room but creates no delivery; that is
  intentional. Resume and send a new request to start work.
- The lead status badge **Discuss** is fixed; there is no missing Develop switch.
- An existing lead with legacy `permission: develop` is intentionally loaded as
  Discuss-only. This is a privilege reduction, not silent elevation.
- A missing model/credential is reported before runtime launch; a catalog listing
  never verifies inference.
- The agent email is not visible through GitHub’s API; the login account name
  `RequieMa-Agent` is the observable identity.

## How to update this register

When you observe an item in another project:

1. Add a dated note under the item: exact command/action, observed behavior, expected
   behavior, and whether it reproduced.
2. Do not change **Status** to Fixed without a regression test and a commit.
3. If a design document claims a feature, check this register and the tests first;
   design text is not implementation evidence.
4. Keep tokens, keys and private message text out of this file.
