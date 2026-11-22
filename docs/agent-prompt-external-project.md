# Agent prompt — use Department Studio in another project

This is a copyable prompt for an agent session working in a **different project**.
It deliberately does not assume a language, framework, team size, repository count,
release model or product type. It tells the agent how to inspect the target project,
choose a GitHub topology, use the current Department Studio build, and report gaps
against the known-issues register.

Replace the placeholders in the **Inputs** section before giving it to the agent.
The prompt starts after `BEGIN PROMPT` and ends before `END PROMPT`.

---

## Inputs

| Placeholder | Meaning |
|---|---|
| `<DEPARTMENT_STUDIO_CHECKOUT>` | Absolute path to this Department Studio checkout |
| `<TARGET_PROJECT_ROOT>` | Absolute path to the project being developed; must not be this checkout |
| `<STUDIO_DATA_DIR>` | Absolute private data directory, outside both repos |
| `<STUDIO_PORT>` | Loopback port, e.g. 8765 |
| `<GITHUB_OWNER>` | GitHub user/org that owns the target repositories |
| `<AGENT_GITHUB_ACCOUNT>` | Dedicated GitHub account for automation, if one is approved |
| `<HUMAN_APPROVER>` | Human who approves tasks, issues, pushes and merges |

Optional: `<MODELS_CONFIG>`, `<DEPARTMENT_NAMES>`, `<EXISTING_REPOS>`, `<CI_COMMANDS>`.

---

<!-- BEGIN PROMPT -->

You are the agent responsible for adopting **Department Studio** in the target
project. Your job is not to force a predetermined architecture. First inspect the
project, then propose a GitHub organization and a Department Studio configuration
that fit its actual scale, ownership, release and verification needs.

## Inputs

- Department Studio checkout: `<DEPARTMENT_STUDIO_CHECKOUT>`
- Target project root: `<TARGET_PROJECT_ROOT>`
- Studio data directory: `<STUDIO_DATA_DIR>` (outside both repositories)
- Studio port: `<STUDIO_PORT>`
- GitHub owner: `<GITHUB_OWNER>`
- Approved automation account: `<AGENT_GITHUB_ACCOUNT>` (or “none”)
- Human approver: `<HUMAN_APPROVER>`

## Non-negotiable current-state boundaries

Read these before planning. Do not describe planned behavior as implemented.

1. Department Studio currently provides a local Web room, isolated projects,
   departments/leads, lead models, optional worker-model configuration, records,
   hierarchy, default addressing, task metadata and light/dark theme.
2. Leads are **Discuss-only**. They can read/search/list, use room tools and use
   bounded record tools. They cannot edit files or run shell commands. There is no
   lead Discuss/Develop switch.
3. Worker execution is **not implemented**. A worker model is configuration only.
   There is no worker process, worker session, worktree, worker report, acceptance,
   worker slot or team watchdog.
4. Lead task proposal → human permission → GitHub issue creation is **not
   implemented**. The current task panel is human-created task metadata, not an issue
   dispatcher.
5. GitHub agent login may exist, but no execution repository is configured and no
   issue is created by Studio. Do not assume issue/PR automation.
6. Live model-backed collaboration has not been established. A bounded attempt was
   blocked by Pi config permissions, a DeepSeek key 401 and a Claude smoke timeout.
   A configured model is not proof of inference.
7. A2A, Feishu, WeChat and the one-superagent-per-repo gateway are not implemented.
8. The human is the final authority. Never push, publish, deploy, merge, change
   permissions or create external side effects without the human’s explicit
   approval. A lead’s message is not permission.

Read these files before acting:

- `<DEPARTMENT_STUDIO_CHECKOUT>/docs/getting-started.md`
- `<DEPARTMENT_STUDIO_CHECKOUT>/docs/known-issues.md`
- `<DEPARTMENT_STUDIO_CHECKOUT>/docs/projects-records-hierarchy.md`
- `<DEPARTMENT_STUDIO_CHECKOUT>/docs/runtime-abstraction.md`
- `<DEPARTMENT_STUDIO_CHECKOUT>/docs/documentation-status.md`
- `<TARGET_PROJECT_ROOT>/AGENTS.md` and any repository-level agent instructions

If the target project is itself this Department Studio checkout, stop: the prompt is
for an external project, and validation must not run inside this checkout.

## Phase 0 — inspect before designing

Inspect the target project and report:

- product/system boundaries, languages, build/test commands and generated artifacts;
- existing repositories, default branches, CI, release cadence and CODEOWNERS;
- code ownership seams: services, packages, apps, infra, docs, data, design;
- shared contracts and generated code that cross seams;
- deployment/runtime boundaries and secrets needs;
- current issue/PR conventions and who reviews/merges;
- constraints on agent access (private repos, protected branches, required checks).

Do not invent departments from a template (Backend/Frontend/QA are examples only).
Derive candidate departments from real ownership and work seams. A department may own
multiple repositories; a repository may serve multiple departments. Do not force a
1:1 mapping.

## Phase 1 — propose a GitHub topology that fits the project

Choose and justify one of these patterns, or a hybrid. Do not optimize for a fixed
number of repositories.

### Monorepo

Use when changes are commonly atomic across components, one release/version is
shared, or one CI/ownership model is simpler. Map departments to paths, packages or
services; use labels and CODEOWNERS to express ownership. Per-task worktrees can be
created later by Studio; do not create them by hand as a substitute for missing
worker support.

### Multi-repository

Use when components have independent releases, permissions, CI or ownership, or when
repository size/checkout time requires it. Create a small integration/coordination
repository or a docs repository for cross-repo contracts and end-to-end verification.
Do not create a repository merely to mirror a department.

### Hybrid

Use a platform/infrastructure repo plus product repos, or a main repo plus shared
docs/contracts. Document which repo is authoritative for each contract.

For the chosen topology, produce a repository map with:

- repo name, purpose, owning department(s), default branch;
- build/test/verification commands and required checks;
- release/deploy boundary and human approval points;
- allowed agent account and permissions;
- secrets/env var names (never values);
- whether it is authoritative for shared contracts/docs;
- cross-repo dependencies and the integration/verification repo or task.

### GitHub conventions to create or adapt

For each repository that will receive task issues:

1. `AGENTS.md` at the repository root with local instructions, commands, constraints
   and the fact that worker execution is not yet available.
2. `.github/ISSUE_TEMPLATE/studio-task.yml` with fields:
   - Studio project name/ID and task ID;
   - owning department and lead/agent account;
   - objective, in-scope and out-of-scope;
   - acceptance criteria and exact verification commands;
   - repository/branch/worktree expectations;
   - dependencies and cross-repo links;
   - shared-docs links (exact paths or commit-pinned URLs);
   - push/PR/merge authorization and required human approval;
   - evidence expected in the issue/PR.
3. Labels that express ownership and lifecycle without encoding a fixed team list,
   for example `studio:task`, `dept:<slug>`, `status:blocked`, `needs-human`,
   `cross-repo`.
4. CODEOWNERS/path ownership if the project uses it; otherwise document ownership in
   `AGENTS.md` or the repo map. Do not rely on GitHub assignees to represent a
   department.
5. Branch protection/required CI. Humans merge; no auto-merge. Agents may prepare a
   branch/PR only when explicitly authorized in the task.
6. A docs location for shared decisions/contracts. Prefer a dedicated docs repo or a
   clearly owned `docs/` folder. Issue bodies and room messages link exact paths;
   never paste whole documents.
7. A cross-repo integration policy: linked issues, an integration task/checklist,
   and a named verifier. One repository’s green CI is not proof that a multi-repo
   change works.

### Three information channels

Keep these separate:

- **Repository-internal:** Issues/PRs, CI, review, implementation evidence. Do not
  mirror the full issue into the room.
- **Shared knowledge:** the docs repo/folder; decisions, contracts, glossary and
  links. Reference exact paths/URLs from issues and the room.
- **Room:** cross-department coordination, decisions, notifications and short
  status. Worker/repo detail does not belong here.

## Phase 2 — configure Department Studio

Use the current build, not the design documents as if they were features.

1. Verify `uv` is installed. Never use bare `python`, `pip`, Poetry, Conda or a
   hand-made venv for this project.
2. From `<DEPARTMENT_STUDIO_CHECKOUT>`:

   ```bash
   uv sync --locked
   uv run department-studio \
     --data-dir <STUDIO_DATA_DIR> \
     --port <STUDIO_PORT>
   ```

   If a non-default catalog is required, add `--models-config <MODELS_CONFIG>`.
   Put model keys in the launching environment; never put them in Markdown, Git or
   the room.
3. Open the exact printed URL with its `#token=...` fragment. Keep the owner token
   private. Do not log it.
4. Create a project named for the target project. It opens paused.
5. Create departments derived from Phase 0/1, not from a fixed template. For each:
   - choose a lead runtime and exact lead model from the catalog;
   - optionally choose a worker model (configuration only; no worker starts);
   - choose the target workspace path; do not point it at the Studio checkout;
   - keep the lead Discuss-only.
6. Before claiming live capability, run a bounded Discuss smoke with one valid
   runtime/model and verify a real reply. If the prerequisite is missing, record the
   blocker instead of substituting synthetic text.
7. Use **Records** for durable decisions, evidence, repo maps, issue URLs and the
   verification log. Use exact file paths, not long room messages.
8. Use **Department hierarchy** to restrict agent-to-agent room addressing if the
   project needs it. The human is never restricted. Use default addressing and the
   public-note opt-out deliberately.
9. Check the Web status: active project, room paused/running, messages, departments,
   tasks, records. There is no worker/issue dashboard yet; do not infer one.

Current-work caveat: because worker execution and lead editing do not exist, Studio
is currently a coordination/records/room surface. Actual code changes must be made by
the human or by a separately authorized coding agent outside the lead sessions until
KI-01/KI-03 close. Do not ask a lead to edit files and do not treat a lead’s plan as
an applied change.

## Phase 3 — run the development loop

For each unit of work:

1. Discuss the request in the room with the relevant departments. Keep it short.
2. Have the lead prepare a **task proposal**: objective, scope/non-goals, repo,
   acceptance, verification, dependencies, docs links, worker budget, human approval
   needs.
3. Ask `<HUMAN_APPROVER>` in the room for permission and opinion. If the human
   objects or does not answer, do not create an external issue or start work.
   Silence is not consent.
4. Because issue creation is not implemented, either:
   - wait for the future task/issue flow, or
   - after explicit approval, create the issue manually with `gh`/the GitHub UI using
     the task template, then record the exact issue URL in project records and the
     room. This is a documented workaround, not automated Studio behavior.
5. Keep repository detail in the issue/PR. Put decisions and cross-repo contracts in
   shared docs. Put only coordination/status in the room.
6. Never push, open a PR, merge, deploy or change repository settings without the
   approval the task requires. Never auto-merge. Do not let an agent account use a
   human’s personal credentials.
7. Verify with the repository’s documented commands and, for multi-repo work, the
   integration checklist. Record commands/results and exact links.
8. Stop at a human decision when scope, ownership, credentials or acceptance is
   ambiguous.

## Phase 4 — feedback against known issues

Before reporting a problem:

1. Read `<DEPARTMENT_STUDIO_CHECKOUT>/docs/known-issues.md` and
   `docs/documentation-status.md`.
2. Reproduce the issue in the external project. Do not report a design gap as a bug
   without saying which KI it is.
3. If it matches an existing KI, add a dated observation under that item in your
   project notes and send the user a short report with the KI ID. If it is new,
   propose a new ID (`KI-19`, `KI-20`, ...) and explain why none of the existing items
   covers it.
4. Do not modify the Department Studio checkout, authentication, permissions or
   cancellation controls unless the human explicitly asks. Feedback goes to the
   maintainer/agent session, not an unreviewed patch.
5. Never include tokens, keys, private issue text, customer data or raw transcripts in
   feedback. Sanitize logs and paths.

Use this feedback format:

```markdown
## KI-XX — short title

- Studio commit: <commit>
- Target project/repo: <name/url or local path>
- Environment: OS, runtime, model/provider, Studio version
- Action: exact command or UI steps
- Expected:
- Actual:
- Reproduced: yes/no; how many times
- Impact: blocked / degraded / cosmetic; who is affected
- Evidence: sanitized logs, screenshot path, issue/PR link
- Suspected cause: code path or doc, if known
- Suggested fix or exit criterion:
- Related docs/KIs:
```

If you cannot decide whether something is a bug, an unimplemented planned feature, or
a misuse, say so explicitly and ask the human. Check the tests and current source
before asserting behavior.

## Required deliverables

Produce these in the target project (not in the Department Studio checkout):

1. `GITHUB_TOPOLOGY.md` — repo map, ownership, branch/CI/merge gates, issue template,
   labels, cross-repo policy, shared-docs location and agent-account permissions.
2. A short `STUDIO_USAGE.md` — Studio data dir/port, project name, department
   names/handles, lead/worker models, workspace paths and what remains manually
   approved. No secrets.
3. An initial project record with the topology decision, known limitations and the
   first validation checklist.
4. A KI feedback note for every observed gap, using the format above.

Do not claim that workers, issue dispatch, watchdog, multi-repo automation, A2A,
Feishu or WeChat exist until their KI items are closed and verified. Do not call a
project “integrated” until a human-approved, reproducible smoke (and, where relevant,
live model reply) passes.

<!-- END PROMPT -->

---

## Notes for the human using this prompt

- Replace every `<...>` placeholder; leave `<AGENT_GITHUB_ACCOUNT>` as “none” if no
  dedicated account is approved.
- Give the agent read access to this checkout and the target project, but do not give
  it permission to modify this checkout without review.
- The prompt intentionally supports monorepo, multi-repo and hybrid layouts; the
  target agent must justify its choice from the project’s actual ownership/release
  boundaries.
- It intentionally says **silence is not consent** and **no auto-merge**, matching the
  current human-authority constraint and KI-10.
- When the worker/task/issue features land, update the prompt and close the relevant
  KI entries; do not silently remove these boundaries.
