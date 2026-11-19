# Department Studio — project brief

Status: bootstrap design approved, including user-defined department names; implementation plan ready for execution handoff.
Working name: Department Studio.

## Goal

Give an individual a shared workspace with persistent AI departments: the visible collaboration of QBuddy without enterprise administration, and DSH-like task ownership and worker delegation across different disciplines.

## Confirmed requirements

- The user is the project lead and final authority. There is no AI project boss above the departments.
- The primary interaction is a shared chat room.
- The user can address a specific department with an `@mention`.
- During first-run setup, the user names departments and chooses their handles; Backend/Frontend are examples, not fixed department types. Renaming preserves department identity, sessions and historical message attribution.
- Departments can visibly discuss requirements and partition work.
- Each department maintains responsibility for its domain and delegates task-specific work to workers.
- The user can take over a task personally.
- The user should not need to manage other people's agents, invitations, hosts, or routine worker provisioning.
- Start by designing and building a tiny proof of concept, not a full enterprise platform.
- Department Studio itself is the first demo project: use its department leads to develop the rest of the application once the communication bootstrap works.
- First enable real communication between different department leads.
- Provide a UI to configure each lead's model and workspace/repository, alongside its identity and department role.
- All project Python code, environments, dependencies and development commands must be managed through `uv` only. See `AGENTS.md`.
- Pi is the first agent runtime. The architecture must support other agent runtimes later through an abstraction rather than coupling department identity or room behavior to Pi.
- Approved integration boundary: runtime-neutral core with a native Pi RPC adapter first; defer A2A client/server interoperability to a later increment.

## Development sequence

1. **Bootstrap:** design and implement the smallest lead-configuration UI and shared chat that allow real model-backed leads to communicate. Pi RPC is selected behind a runtime-neutral interface; detailed model configuration and room behavior are proposed in the bootstrap design.
2. **Use the bootstrap:** the user directs those leads in the room to discuss, partition and implement Department Studio's next increments. This must be an actual development path, not a scripted demo.
3. **Extend incrementally:** add worker delegation, explicit task ownership/takeover, integration and other capabilities through reviewed, tested increments.

This sequence does not introduce an AI project boss. Message delivery and execution bookkeeping are software responsibilities; project direction remains with the user. Automated tests may use deterministic test doubles, but they do not replace demonstrating the real lead communication path.

## Longer-term direction, not committed POC scope

- A game involving design, engineering, art, audio and narrative remains a later example; the initial demo is Department Studio itself.
- Departments may own separate repositories.
- A central project repository may pin compatible department versions, using submodules or another versioned dependency mechanism.
- Integration checks must establish that departmental outputs work together; repository structure alone does not provide that guarantee.

## Approved design and remaining setup

- Approved scope and acceptance criteria: `docs/superpowers/specs/2026-11-19-bootstrap-design.md`.
- Protocol rationale: `docs/research/a2a-and-runtime-adapters.md`.
- Runtime-neutral core, Pi RPC first, and A2A deferred.
- Existing Pi model configuration; local Python/static-UI application; explicit mentions and Discuss-first permissions.
- The user will choose actual department names, models and workspace paths in the UI. No model or department is silently preselected for live execution.
- Full task ownership and multi-repository automation follow the communication bootstrap.
- Implementation plan: `docs/superpowers/plans/2026-11-19-bootstrap-implementation.md`.

## Design and delivery checklist

- [x] Review the prior QBuddy/DSH analysis and capture the user's updated intent.
- [x] Create a dedicated project folder.
- [x] Offer optional browser-based visual exploration; no consent to launch it has been given.
- [x] Resolve essential requirements and capture approved defaults.
- [x] Compare integration approaches; user approved Pi RPC behind a runtime-neutral core, with A2A deferred.
- [x] Present the POC design and obtain approval, including custom department naming.
- [x] Write and review a proposed bootstrap specification; clarify timeout safety and Develop-mode authority.
- [x] Obtain review of the written specification before implementation.
- [x] Prepare and self-review the implementation and verification plan.
- [ ] Implement the approved scope, test it, and report demonstrated behavior and limitations.

No application code, dependency installation, model calls, or external repository changes have been made.
