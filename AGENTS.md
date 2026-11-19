# Department Studio — development constraints

## Python: uv only

This is a user requirement, not an optional preference.

- Manage every project Python interpreter/environment and dependency through `uv`.
- When Python implementation is introduced, declare dependencies in `pyproject.toml` and maintain `uv.lock`.
- Use `uv add` for runtime dependencies and `uv add --dev` for development dependencies.
- Use `uv sync` to synchronize the project environment.
- Run Python code and Python-based tools through `uv run`, for example `uv run python`, `uv run pytest`, and `uv run ruff check .` when those tools are configured.
- Do not use bare `python`, `python3`, `pip`, `pip3`, Poetry, Pipenv, Conda, or manually created virtual environments for project development.
- Do not install project Python dependencies into a global/system environment.
- If `uv` is unavailable, report the blocker rather than silently using another manager.
- This requirement does not force non-Python frontend code to use Python tooling; any frontend toolchain remains a separate design choice.

## Product authority

- The human user is the project lead and final authority; do not introduce an autonomous AI boss above department leads.
- Start with no built-in departments. The user names departments and chooses their handles, roles, models and workspaces during initial setup. Backend/Frontend/QA are examples only; do not hard-code names or map behavior from names.
- Department IDs must be independent of display names and handles. Renaming must preserve sessions and relationships; historical messages retain their original sender labels.
- The shared chat is the primary interaction surface. Support addressing departments and, as task execution is introduced, human takeover.
- Department leads can collaborate and delegate within authorized scope. An agent's message is not automatically permission for arbitrary execution or broader access.
- A configured workspace path identifies where work happens; it is not an OS security sandbox.

## Runtime extensibility

- Start with Pi, as selected by the user; retain an abstraction for other agent runtimes later.
- Keep persistent department identity and room behavior independent of Pi-specific session IDs, commands and event shapes.
- Distinguish agent runtime selection from model/provider selection.
- Approved architecture: a runtime-neutral core, a Pi RPC adapter first, and an A2A interoperability boundary later. Do not implement A2A in the bootstrap or claim conformance before it is implemented and verified.

## Bootstrap and self-development

- Department Studio is its own first demo project.
- First establish real department-lead communication and UI configuration of each lead's model and workspace/repository.
- Then use that mechanism, under user direction, to develop subsequent features.
- Prefer a narrow, verifiable bootstrap over enterprise administration, a full worker fleet, or multi-repository release automation in the first increment.
- Do not describe simulated agent responses as real model-backed collaboration.
- Test and review self-development changes before applying them to the running application. Self-development does not authorize silent changes to execution permissions or approval controls.

## Current phase

The bootstrap design is approved, including user-defined department names. Proceed with implementation planning and test-driven implementation of `docs/superpowers/specs/2026-11-19-bootstrap-design.md`. Pi RPC is the first adapter; A2A is deferred. Use deterministic backends and subprocess fixtures for automated tests. Live model calls require user-selected models and explicit authorization; do not launch unrestricted agents.
