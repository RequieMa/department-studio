import asyncio
from dataclasses import replace

import pytest

from department_studio.backends.base import (
    BackendCapabilities,
    ContextOutcome,
    RunOutcome,
)
from department_studio.backends.registry import RuntimeRegistry, RuntimeUnavailable
from tests.factories import create_lead


class NamedBackend:
    def __init__(self, name, *, available=True, capability=True):
        self.name = name
        self._available = available
        self.capability = capability
        self.requests = []
        self.cancelled = []
        self.closed = 0

    def available(self):
        return self._available

    def capabilities(self):
        return BackendCapabilities(
            self.capability, self.capability, True, True, self.capability, False
        )

    async def run(self, request, emit):
        self.requests.append(request.id)
        return RunOutcome("completed", text=self.name)

    async def prepare_context(self, request, emit):
        return ContextOutcome("kept")

    async def cancel(self, run_id):
        self.cancelled.append(run_id)
        return True

    async def close(self):
        self.closed += 1


def request(store, tmp_path, kind, handle="atlas"):
    lead = create_lead(store, tmp_path, handle=handle)
    return replace(lead, backend_kind=kind)


async def no_events(event):
    pass


async def test_each_department_routes_to_its_selected_runtime(store, tmp_path):
    pi, claude, deepseek = NamedBackend("pi"), NamedBackend("claude"), NamedBackend("deepseek")
    registry = RuntimeRegistry({"pi": pi, "claude": claude, "deepseek": deepseek})
    from department_studio.backends.base import RunRequest

    for index, kind in enumerate(("pi", "claude", "deepseek")):
        lead = request(store, tmp_path, kind, handle=f"lead-{index}")
        run = RunRequest(
            f"run-{index}",
            1,
            lead,
            "prompt",
            "http://127.0.0.1:8765/api/bridge/messages",
            "token",
        )
        assert (await registry.run(run, no_events)).text == kind
    assert pi.requests == ["run-0"]
    assert claude.requests == ["run-1"]
    assert deepseek.requests == ["run-2"]
    await registry.close()
    assert [pi.closed, claude.closed, deepseek.closed] == [1, 1, 1]


class BlockingBackend(NamedBackend):
    def __init__(self, name):
        super().__init__(name)
        self.gate = asyncio.Event()

    async def run(self, request, emit):
        self.requests.append(request.id)
        await self.gate.wait()
        return RunOutcome("interrupted")

    async def cancel(self, run_id):
        self.cancelled.append(run_id)
        self.gate.set()
        return True


async def test_cancel_is_routed_to_the_owning_runtime(store, tmp_path):
    pi, claude = BlockingBackend("pi"), BlockingBackend("claude")
    registry = RuntimeRegistry({"pi": pi, "claude": claude})
    from department_studio.backends.base import RunRequest

    run = RunRequest("run-1", 1, request(store, tmp_path, "claude"), "prompt", "url", "token")
    task = asyncio.create_task(registry.run(run, no_events))
    await asyncio.sleep(0)  # Let the registry record the owner before cancel.
    assert await registry.cancel("run-1") is True
    assert await task
    assert claude.cancelled == ["run-1"]
    assert pi.cancelled == []
    assert await registry.cancel("already-finished") is True
    await registry.close()


async def test_single_backend_serves_every_runtime_and_unavailable_is_reported(store, tmp_path):
    backend = NamedBackend("shared")
    registry = RuntimeRegistry.single(backend)
    from department_studio.backends.base import RunRequest

    run = RunRequest("run-1", 1, request(store, tmp_path, "deepseek"), "prompt", "url", "token")
    assert (await registry.run(run, no_events)).text == "shared"
    assert {info.kind for info in registry.runtimes()} == {"pi", "claude", "deepseek"}
    assert all(info.available for info in registry.runtimes())
    await registry.close()
    assert backend.closed == 1

    unavailable = RuntimeRegistry(
        {"pi": NamedBackend("pi", available=False), "claude": NamedBackend("claude")}
    )
    infos = {info.kind: info for info in unavailable.runtimes()}
    assert infos["pi"].available is False
    assert infos["deepseek"].available is False
    with pytest.raises(RuntimeUnavailable, match="not installed"):
        unavailable.backend_for("deepseek")
    await unavailable.close()
