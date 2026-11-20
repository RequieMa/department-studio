import asyncio
import json
import socket

import httpx
import uvicorn

from department_studio.api import create_app
from department_studio.backends.pi import PiBackend
from department_studio.config import Settings
from department_studio.service import RoomService
from tests.factories import create_lead
from tests.fakes import until
from tests.test_rpc import FAKE_PI


async def test_overflow_resume_then_new_request_uses_fresh_native_conversation(store, tmp_path):
    lead = create_lead(store, tmp_path)
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.6)
    native = tmp_path / "sessions" / lead.id / "fixture.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text("Retained old private transcript\n")
    work = tmp_path / "unfinished-work.txt"
    work.write_text("Retain this edit\n")
    store.resume()
    old = store.post_human_message("@atlas old failed request")
    delivery = store.claim_delivery()
    store.finish_delivery(
        delivery.id, delivery.generation, "failed", native_session_ref=str(native)
    )
    trace = tmp_path / "trace.jsonl"
    backend = PiBackend(
        settings,
        command_prefix=FAKE_PI,
        extra_env={
            "FAKE_PI_MODE": "context_overflow",
            "FAKE_PI_TRACE": str(trace),
        },
    )
    service = RoomService(store, backend, settings)
    await service.start()
    try:
        service.resume()
        await until(lambda: not store.paused)
        fresh = store.get_lead(lead.id)
        assert fresh.conversation_id != lead.conversation_id
        assert store.list_context_checks()[0].state == "reset"
        assert len(store.list_deliveries()) == 1
        assert store.get_message(old.message_id).text == "@atlas old failed request"
        receipt = service.post_human("@atlas report current status only")
        await until(lambda: store.list_deliveries()[-1].state == "completed")
        assert store.list_deliveries()[-1].message_id == receipt.message_id
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        launches = [record for record in records if "argv" in record]
        assert len(launches) == 2
        assert "--no-tools" in launches[0]["argv"]
        assert lead.conversation_id in launches[0]["argv"]
        assert fresh.conversation_id in launches[1]["argv"]
        prompts = [record for record in records if record.get("type") == "prompt"]
        assert len(prompts) == 1
        prompt = json.loads(prompts[0]["message"].split("\n", 1)[1])
        assert prompt["input"]["text"] == "@atlas report current status only"
        assert prompt["continuity"]["native_session_ref"] == str(native)
        assert len(store.list_session_refs(lead.id)) == 2
        assert native.read_text() == "Retained old private transcript\n"
        assert work.read_text() == "Retain this edit\n"
    finally:
        await service.close()


async def test_service_pause_confirms_fake_pi_exit_and_releases_adapter_state(store, tmp_path):
    lead = create_lead(store, tmp_path)
    trace = tmp_path / "trace.jsonl"
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.6)
    backend = PiBackend(
        settings,
        command_prefix=FAKE_PI,
        extra_env={"FAKE_PI_MODE": "hang", "FAKE_PI_TRACE": str(trace)},
    )
    service = RoomService(store, backend, settings)
    await service.start()
    service.resume()
    try:
        await until(lambda: not store.paused)
        service.post_human(f"@{lead.handle} wait for a manual stop")
        await until(lambda: trace.exists() and '"type": "prompt"' in trace.read_text())
        execution = next(iter(backend._runs.values()))
        await service.pause()
        await until(lambda: store.list_deliveries()[0].state == "interrupted")
        await until(lambda: not backend._runs and not backend._clients)
        assert execution.rpc.process.returncode is not None
        assert not list((tmp_path / "sessions" / lead.id).glob("bridge-*"))
    finally:
        await service.close()


async def test_fake_pi_through_real_http_bridge_addresses_second_department(store, tmp_path):
    """Actual process, HTTP and persistence integration; model inference is synthetic."""
    first = create_lead(store, tmp_path, "atlas")
    second = create_lead(store, tmp_path, "canvas", name="Canvas", model_id="model-b")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        settings = Settings(
            pi_executable="/bin/true", port=port, data_dir=tmp_path, stop_timeout_seconds=0.6
        )
        backend = PiBackend(settings, command_prefix=FAKE_PI, extra_env={"FAKE_PI_MODE": "bridge"})
        app = create_app(settings, store=store, backend=backend, owner_token="integration-owner")
        server = uvicorn.Server(
            uvicorn.Config(
                app, lifespan="on", log_level="error", access_log=False, proxy_headers=False
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            await until(lambda: server.started)
            async with httpx.AsyncClient(
                base_url=settings.origin, headers={"Authorization": "Bearer integration-owner"}
            ) as client:
                assert (await client.post("/api/room/resume")).status_code == 200
                await until(lambda: not store.paused)
                root = await client.post(
                    "/api/messages", json={"text": "@atlas discuss a small API"}
                )
                assert root.status_code == 200
                await until(
                    lambda: (
                        len(store.list_deliveries()) == 2
                        and all(d.state == "completed" for d in store.list_deliveries())
                    )
                )
                state = (await client.get("/api/state")).json()
                peer = next(m for m in state["messages"] if m["text"] == "Synthetic peer request")
                assert peer["sender_id"] == first.id
                assert peer["recipient_ids"] == [second.id]
                assert (
                    len([m for m in state["messages"] if m["text"] == "Synthetic public reply"])
                    == 2
                )
                assert len({d["chain_id"] for d in state["deliveries"]}) == 1
                assert len({d["conversation_id"] for d in state["deliveries"]}) == 2
                assert store.get_chain(peer["chain_id"]).reserved == 2
                assert all(
                    store.list_session_refs(lead.id)[0]["native_session_ref"]
                    for lead in (first, second)
                )
        finally:
            server.should_exit = True
            async with asyncio.timeout(5):
                await serving
        assert app.state.service.shutdown_confirmed

        restarted = create_app(
            settings,
            store=store,
            backend=PiBackend(
                settings, command_prefix=FAKE_PI, extra_env={"FAKE_PI_MODE": "bridge"}
            ),
        )
        async with restarted.router.lifespan_context(restarted):
            assert store.paused
            assert len(store.list_messages()) == 4
            assert restarted.state.owner.token != "integration-owner"
            restarted.state.service.resume()
            await until(lambda: not store.paused)
            assert len(store.list_deliveries()) == 2
            assert not restarted.state.service.backend._runs
