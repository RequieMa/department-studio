"""Per-department agent-runtime selection over one normalized backend contract."""

import asyncio
from collections.abc import Mapping

from department_studio.backends.base import (
    AgentBackend,
    BackendCapabilities,
    ContextOutcome,
    ContextRequest,
    Emit,
    RunOutcome,
    RunRequest,
    RuntimeInfo,
)
from department_studio.models import RUNTIMES


class RuntimeUnavailable(RuntimeError):
    """A department selected a runtime this installation cannot start."""


class RuntimeRegistry:
    """Route each request by the department's persisted runtime selection.

    A single injected backend (tests and embedders) serves every runtime kind.
    Real installations provide one backend per kind.
    """

    def __init__(self, backends: Mapping[str, AgentBackend], *, single: bool = False):
        self._backends = dict(backends)
        self._single = single
        self._owners: dict[str, AgentBackend] = {}
        self._closed = False

    @classmethod
    def single(cls, backend: AgentBackend) -> "RuntimeRegistry":
        return cls({kind: backend for kind in RUNTIMES}, single=True)

    def backend_for(self, kind: str) -> AgentBackend:
        backend = self._backends.get(kind)
        if backend is None:
            raise RuntimeUnavailable(
                f"The {RUNTIMES.get(kind, kind)} runtime is not installed in this build."
            )
        return backend

    def _available(self, backend: AgentBackend) -> bool:
        probe = getattr(backend, "available", None)
        if probe is None:
            return True
        try:
            return bool(probe())
        except Exception:
            return False

    def runtimes(self) -> list[RuntimeInfo]:
        result = []
        for kind, name in RUNTIMES.items():
            backend = self._backends.get(kind)
            if backend is None:
                result.append(
                    RuntimeInfo(
                        kind,
                        name,
                        False,
                        BackendCapabilities(False, False, False, False, False, False),
                    )
                )
                continue
            result.append(
                RuntimeInfo(
                    kind,
                    name,
                    self._available(backend),
                    backend.capabilities(),
                )
            )
        return result

    def capabilities(self) -> BackendCapabilities:
        # The room as a whole supports what any configured runtime supports.
        infos = [info for info in self.runtimes() if info.available]
        return BackendCapabilities(
            model_selection=any(info.capabilities.model_selection for info in infos),
            local_workspace=any(info.capabilities.local_workspace for info in infos),
            cancellation=any(info.capabilities.cancellation for info in infos),
            persistent_conversation=any(
                info.capabilities.persistent_conversation for info in infos
            ),
            room_bridge=any(info.capabilities.room_bridge for info in infos),
            context_maintenance=any(info.capabilities.context_maintenance for info in infos),
        )

    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome:
        backend = self.backend_for(request.lead.backend_kind)
        self._owners[request.id] = backend
        try:
            return await backend.run(request, emit)
        finally:
            self._owners.pop(request.id, None)

    async def prepare_context(self, request: ContextRequest, emit: Emit) -> ContextOutcome:
        backend = self.backend_for(request.lead.backend_kind)
        self._owners[request.id] = backend
        try:
            return await backend.prepare_context(request, emit)
        finally:
            self._owners.pop(request.id, None)

    async def cancel(self, run_id: str) -> bool:
        backend = self._owners.get(run_id)
        if backend is None:
            return True
        return await backend.cancel(run_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        unique = list({id(backend): backend for backend in self._backends.values()}.values())
        results = await asyncio.gather(
            *(backend.close() for backend in unique), return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("Agent runtime shutdown could not confirm process exit.")

    def list_models(self, workspace=None):
        # The catalog, not a runtime, owns model listing.
        return []
