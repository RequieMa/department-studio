# Documentation and plan status — November 21, 2026

## Verdict

The approved bootstrap core and the later runtime/catalog, task, project, records,
hierarchy, addressing and theme increments are implemented and covered by automated
tests. The remaining gaps are **live acceptance, independent review, and explicitly
deferred increments** — not missing core code.

This document is the index for deciding whether a plan is complete, historical, or
deferred. Historical documents keep their original evidence; do not read their old
test counts as current.

## Bootstrap plan completion

| Area | Status | Evidence / note |
|---|---|---|
| uv foundation, config, data lock | Complete | `tests/test_config.py`; pyproject/uv.lock |
| Identity, SQLite, deletion, migrations | Complete | schema v0→v4 tests; `backend/DELETION.md` |
| Runtime-neutral scheduling, stop, restart | Complete | service/RPC/context tests |
| Pi RPC adapter and bridge | Complete with one live blocker | installed Pi config dir is read-only in this environment (`EACCES`); fixture tests pass |
| Claude Code adapter | Implemented, not live-verified | Claude smoke did not finish in the verification window |
| DeepSeek Harness adapter | Implemented, not live-verified | copied headless profile + configured key returned HTTP 401 |
| HTTP/security/launcher | Complete | API/security/packaging tests |
| Browser UI setup/room | Complete | 21 Chromium tests |
| Runtime/model catalog extension | Complete | 350 ordinary tests; no qgenie in source |
| Ongoing tasks + decisions | Complete and merged | schema v3, API/UI/browser tests |
| Projects/history/switch/delete | Complete | isolated Store/Service per project; API/UI/browser tests |
| Records + bridge tools | Complete | owner API/UI, Pi extension and MCP tools; 512 KiB bounded records |
| Department hierarchy | Complete | schema v4 complete-graph backfill; peer-message enforcement |
| Default addressing + public note | Complete | persisted `active_recipient_ids`; API/UI tests |
| Peer-message folding | Complete | default collapsed; browser test |
| Dark mode | Complete | system preference + explicit local toggle; browser test |
| Independent spec/quality review | **Outstanding** | user authorized direct TDD; no independent reviewer succeeded |
| Live two-department demonstration | **Outstanding** | bounded attempt blocked by credentials/config; no success claimed |
| A2A client/server | **Deferred** by approved scope | not implemented |
| Progress watchdog | **Deferred** | `docs/watchdog-follow-up.md`; current 300s deadline unchanged |
| Full worker fleet / ownership transfer | **Proposed, not implemented** | [worker teams design](worker-teams-design.md); current tasks are human-facing metadata |
| Multi-repository / GitHub orchestration | **Proposed, not implemented** | phase C in the worker-teams design; superagent-per-repo gateway validated separately |
| A2A | **Evaluated; deferred** | [evaluation section](worker-teams-design.md#7-a2a-evaluation) |

Implementation-plan checkboxes marked unchecked are the per-task **review/commit
gates**, not missing implementation steps. The execution note at the top of the
plan explains why direct TDD replaced independent subagent review. They should not be
counted as "all plan checkboxes green"; they remain process gaps.

## Document status matrix

| Document | Status | What to trust |
|---|---|---|
| `README.md` | Current | operation, all current surfaces, current test counts |
| `AGENTS.md` | Current | project constraints, including projects/records/hierarchy/theme |
| `docs/runtime-abstraction.md` | Current | runtime/model contract and live blockers |
| `docs/projects-records-hierarchy.md` | Current | project layout, records, hierarchy, addressing, v4 |
| `docs/task-integration.md` | Current | task integration and reconciliation evidence |
| `backend/TASKS.md` | Current contract | task API/lifecycle; tasks are schema v3 inside v4 |
| `backend/DELETION.md` | Current contract + historical counts | deletion behavior; its v0/v1 schema account is historical |
| `docs/live-demo.md` | Current guide, updated | bounded live setup and evidence table |
| `docs/verification.md` | Current summary + historical sections | bottom summary is current; early sections are historical |
| `docs/resume-context.md` | Current policy + historical evidence | v4 note added; old counts/paths are historical |
| `docs/superpowers/specs/2026-11-19-bootstrap-design.md` | Approved original scope; partially superseded | use status banner and later-extension links |
| `docs/superpowers/plans/2026-11-19-bootstrap-implementation.md` | Original plan; implementation superseded in details | checkboxes are historical; see completion table above |
| `BRIEF.md` | Original brief; status updated | scope history, not current verification |
| `docs/watchdog-follow-up.md` | Deferred design | not implemented |
| `docs/worker-teams-design.md` | Proposed design | worker teams, watchdog, multi-repo and A2A evaluation; not implemented |
| `docs/superagent-repo-gateway.md` | Validation/proposal | one superagent per repo, GitHub issue/comment mirror, supervisor; not implemented |
| `docs/research/a2a-and-runtime-adapters.md` | Research, implementation note added | A2A still deferred |
| `docs/frontend-integration.md` | Historical evidence | pre-integration candidate; not current |
| `docs/relaunch-integration.md` | Historical evidence | v1-era relaunch; not current |
| `docs/rpc-robustness.md` | Historical evidence | superseded by later RPC/context work |
| `docs/2026-11-20-runtime-audit.md` | Historical audit | keep for incident history; schema note updated |
| `docs/root-integration.md` | Historical bootstrap import | archived room; not current layout |
| `docs/sample-conversation.md` | Current example, updated | public-note behavior corrected |
| `docs/projects-records-hierarchy.md` | Current | see above |

## Gaps and corrections made in this review

1. `docs/runtime-abstraction.md` had been overwritten by a verification copy. It is
   restored from the last good revision and extended with records/project links.
2. `BRIEF.md` still said no implementation/model calls existed. It is now marked as
   historical scope and links current status.
3. The approved spec and implementation plan described one project/Pi-only/provider
   enumeration. They are now explicitly labelled original scope with superseding
   extensions, rather than silently rewriting the approval record.
4. Historical verification documents had no banner and could be mistaken for current
   results. Banners now point to the current summary.
5. `docs/live-demo.md` lacked projects, records, hierarchy, addressing and theme
   steps; it now includes them and records the blocked live attempt.
6. `docs/sample-conversation.md` told the human to end with an unaddressed note. Under
   default addressing that now continues the previous department; it now uses the
   explicit public-note opt-out.
7. `docs/resume-context.md` still showed 238/13/6 and a Pi-only launch path as if
   current. Its policy is current; counts and paths are labelled historical.
8. `backend/DELETION.md` described only v0/v1. Its schema section now points to the
   current v4 baseline while retaining the historical contract evidence.
9. Live attempt evidence is recorded in `docs/verification.md`, including the backup
   path and the Pi/Claude/DeepSeek blockers.

## Enhancements worth doing next

- **Live acceptance** with a writable Pi configuration directory, a valid DeepSeek
  key, and one small Claude Code/DeepSeek Harness request each. Verify model report,
  room bridge, records tools, resume, cancellation and restart.
- **Independent review** of the spec deltas and security-sensitive changes, or an
  explicit decision to keep the prototype self-reviewed.
- **Project deletion UX**: the API requires the project name; the browser currently
  uses a native confirmation and auto-supplies the name. A typed confirmation would
  match the department-deletion pattern.
- **Records editing UI**: humans can create/read; agents can append. Add explicit
  human append/replace if audit editing becomes a requirement.
- **Watchdog** only after the human reviews the replacement deadline policy; current
  300s deadline remains.
- **A2A** only when interoperability becomes an acceptance criterion.
- A lightweight documentation link/status check would catch overwritten or stale
  docs before release.

## Current verification checkpoint

- 350 ordinary tests, 21 Chromium browser tests, 7 Node bridge tests; Ruff and
  formatting clean; wheel build and installed-artifact checks pass.
- Real-database copy migrated v3→v4 with 5 departments, 180 messages and 116
  deliveries preserved; hierarchy backfilled to 10 edges.
- Live attempt: Pi blocked by read-only Pi config; DeepSeek Harness returned 401;
  Claude Code did not finish in the verification window. No successful live call is
  claimed.
- Backup: `artifacts/live-demo-pre-live-2026-11-21-232350/` (git-ignored, SHA256SUMS,
  SQLite integrity `ok`). The live directory was not migrated or restarted.
