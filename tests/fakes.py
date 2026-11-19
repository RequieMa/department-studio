"""Synthetic backends for tests only; never a live collaboration demonstration."""

import asyncio

from department_studio.backends.base import AgentEvent, BackendCapabilities, ModelOption, RunOutcome


class ControlledBackend:
    def __init__(self, *, cancel_mode="confirm"):
        self.requests = []
        self.pending = {}
        self.active = set()
        self.max_active = 0
        self.cancel_mode = cancel_mode
        self.cancel_calls = []
        self.closed = False

    def capabilities(self):
        return BackendCapabilities(True, True, True, True)

    async def list_models(self, workspace):
        return [
            ModelOption("test", "model-a", "Synthetic A"),
            ModelOption("test", "model-b", "Synthetic B"),
        ]

    async def run(self, request, emit):
        self.requests.append(request)
        future = asyncio.get_running_loop().create_future()
        self.pending[request.id] = future
        self.active.add(request.id)
        self.max_active = max(self.max_active, len(self.active))
        await emit(AgentEvent("started", "Synthetic execution"))
        try:
            return await future
        finally:
            self.active.discard(request.id)

    def release(self, request, *, text="Synthetic reply", state="completed", error=None):
        future = self.pending[request.id]
        if not future.done():
            future.set_result(RunOutcome(state, text=text, error=error))

    async def cancel(self, run_id):
        self.cancel_calls.append(run_id)
        if self.cancel_mode == "confirm":
            future = self.pending.get(run_id)
            if future and not future.done():
                future.set_result(RunOutcome("interrupted"))
            return True
        if self.cancel_mode == "hang":
            await asyncio.Event().wait()
        return False

    async def close(self):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_result(RunOutcome("interrupted"))


class AutomaticBackend(ControlledBackend):
    async def run(self, request, emit):
        self.requests.append(request)
        await emit(AgentEvent("started", "Synthetic test execution"))
        await asyncio.sleep(0.02)
        return RunOutcome("completed", text=f"Synthetic test reply from {request.lead.name}.")


async def until(predicate, timeout=10):  # noqa: ASYNC109 -- bounded observation of test state
    async with asyncio.timeout(timeout):
        while not predicate():  # noqa: ASYNC110 -- observes persisted state without production hooks
            await asyncio.sleep(0.005)
