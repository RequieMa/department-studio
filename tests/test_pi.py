import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from department_studio.backends.base import RunRequest
from department_studio.backends.pi import PiBackend
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.factories import create_lead
from tests.fakes import until
from tests.test_rpc import FAKE_PI


@pytest.fixture
def request_factory(store, tmp_path):
    lead = create_lead(store, tmp_path)
    return lambda **changes: replace(
        RunRequest(
            "run-1",
            1,
            lead,
            'Attributed room input follows as JSON data.\n{"input":"/model x"}',
            "http://127.0.0.1:8765/api/bridge/messages",
            "synthetic-runtime-credential",
        ),
        **changes,
    )


@pytest.fixture
def backend_factory(tmp_path):
    def factory(mode="normal"):
        return PiBackend(
            Settings(pi_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.6),
            TEST_CATALOG,
            command_prefix=FAKE_PI,
            extra_env={"FAKE_PI_MODE": mode, "FAKE_PI_TRACE": str(tmp_path / "trace.jsonl")},
        )

    return factory


def records(tmp_path):
    path = tmp_path / "trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def no_events(event):
    pass


async def test_explicit_session_model_workspace_and_restricted_launch_policy(
    backend_factory, request_factory, tmp_path
):
    (tmp_path / "AGENTS.md").write_text("Use uv for all Python commands.")
    backend = backend_factory()
    request = request_factory()
    outcome = await backend.run(request, no_events)
    assert outcome.state == "completed"
    assert outcome.text == "Synthetic public reply"
    launch = records(tmp_path)[0]
    args = launch["argv"]
    assert args[args.index("--session-id") + 1] == request.lead.conversation_id
    assert args[args.index("--session-dir") + 1].endswith(request.lead.id)
    assert args[args.index("--model") + 1] == request.lead.model_id
    assert launch["cwd"] == request.lead.workspace
    assert launch["agent_dir"].startswith(str(tmp_path / "sessions" / request.lead.id))
    config = launch["models_config"]
    assert set(config["providers"]) == {"test"}
    provider = config["providers"]["test"]
    assert provider["api"] == "openai-completions"
    assert provider["baseUrl"] == "https://models.example.invalid/v1"
    assert [model["id"] for model in provider["models"]] == [
        "model-a",
        "model-b",
        "model-c",
        "model-d",
        "fixture",
    ]
    assert provider["models"][0]["contextWindow"] == 128000
    assert launch["bridge_token"] == request.bridge_token
    assert not launch["owner_present"]
    assert set(args[args.index("--tools") + 1].split(",")) == {
        "read",
        "grep",
        "find",
        "ls",
        "send_room_message",
    }
    for flag in (
        "--no-approve",
        "--no-extensions",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--offline",
    ):
        assert flag in args
    assert "--continue" not in args
    assert args.count("-e") == 1
    instructions = args[args.index("--append-system-prompt") + 1]
    assert "Use uv for all Python commands." in instructions
    assert request.lead.role in instructions
    assert "not filesystem isolation" in instructions
    assert "synthetic-runtime-credential" not in outcome.text
    assert outcome.native_session_ref
    await backend.close()


async def test_develop_tools_and_fresh_process_preserve_conversation(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory()
    request = request_factory()
    request = replace(request, lead=replace(request.lead, permission="develop"))
    await backend.run(request, no_events)
    await backend.run(replace(request, id="run-2", bridge_token="second-token"), no_events)
    launches = [r for r in records(tmp_path) if "argv" in r]
    assert len(launches) == 2
    assert {r["bridge_token"] for r in launches} == {request.bridge_token, "second-token"}
    for launch in launches:
        args = launch["argv"]
        assert {"bash", "edit", "write"} <= set(args[args.index("--tools") + 1].split(","))
        assert request.lead.conversation_id in args


async def test_acceptance_and_agent_end_are_not_completion(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("delayed")
    run = asyncio.create_task(backend.run(request_factory(), no_events))
    await until(lambda: any(r.get("checkpoint") == "agent_end" for r in records(tmp_path)))
    assert not run.done()
    assert (await run).state == "completed"


@pytest.mark.parametrize("mode", ["wrong_model", "provider_error", "reject", "startup_exit"])
async def test_failures_are_not_success_and_do_not_leak_errors(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert outcome.text == ""
    assert "secret" not in outcome.error
    if mode == "wrong_model":
        assert not any(r.get("type") == "prompt" for r in records(tmp_path))


async def test_handled_prompt_finishes_without_waiting_for_nonexistent_run(
    backend_factory, request_factory
):
    backend = backend_factory("handled")
    async with asyncio.timeout(3):
        outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "completed" and outcome.text == ""


@pytest.mark.parametrize("mode", ["hang", "stubborn", "queued"])
async def test_cancel_clears_queue_before_abort_and_confirms_child_exit(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    request = request_factory()
    run = asyncio.create_task(backend.run(request, no_events))
    await until(lambda: any(r.get("type") == "prompt" for r in records(tmp_path)))
    assert await backend.cancel(request.id)
    assert (await run).state == "interrupted"
    commands = [r.get("type") for r in records(tmp_path)]
    assert "clear_queue" in commands
    if mode != "stubborn":
        assert commands.index("clear_queue") < commands.index("abort")
    await backend.close()


async def test_dialog_is_canceled_with_visible_diagnostic(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("dialog")
    events = []

    async def capture(event):
        events.append(event)

    assert (await backend.run(request_factory(), capture)).state == "completed"
    assert any("dialog" in e.message.lower() for e in events)
    response = next(r for r in records(tmp_path) if r.get("type") == "extension_ui_response")
    assert response == {"type": "extension_ui_response", "id": "dialog-1", "cancelled": True}


async def test_model_metadata_never_prompts_or_exposes_provider_secrets(backend_factory, tmp_path):
    backend = backend_factory()
    models = await backend.list_models(tmp_path)
    assert [model.id for model in models] == [
        "model-a",
        "model-b",
        "model-c",
        "model-d",
        "fixture",
    ]
    assert all(model.provider == "test" for model in models)
    assert not records(tmp_path)


async def test_missing_room_extension_fails_before_prompt(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("missing_bridge")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "bridge" in outcome.error.lower()
    assert not any(r.get("type") == "prompt" for r in records(tmp_path))


async def test_slow_initialization_is_independent_of_stop_deadline(
    backend_factory, request_factory
):
    backend = backend_factory("slow_start")
    assert (await backend.run(request_factory(), no_events)).state == "completed"


async def test_live_bridge_edits_are_not_applied_until_service_restart(
    backend_factory, request_factory, tmp_path, monkeypatch
):
    source = tmp_path / "source-bridge.ts"
    original = b"// original reviewed bridge source\n"
    source.write_bytes(original)
    monkeypatch.setattr("department_studio.backends.pi.EXTENSION_PATH", source)
    backend = backend_factory()
    source.write_bytes(b"// subsequent unreviewed changes\n")
    assert (await backend.run(request_factory(), no_events)).state == "completed"
    launch = records(tmp_path)[0]
    assert launch["extension_digest"] == hashlib.sha256(original).hexdigest()
