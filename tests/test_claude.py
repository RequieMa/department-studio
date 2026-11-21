import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from department_studio.backends.base import RunRequest
from department_studio.backends.claude import ClaudeBackend
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.factories import create_lead
from tests.fakes import until

FAKE = [sys.executable, str(Path(__file__).with_name("fixtures").joinpath("fake_claude.py"))]


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
        return ClaudeBackend(
            Settings(claude_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.6),
            TEST_CATALOG,
            command_prefix=FAKE,
            extra_env={
                "FAKE_CLAUDE_MODE": mode,
                "FAKE_CLAUDE_TRACE": str(tmp_path / "trace.jsonl"),
            },
        )

    return factory


def records(tmp_path):
    path = tmp_path / "trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def no_events(event):
    pass


async def test_print_mode_uses_catalog_model_bridge_and_bounded_tools(
    backend_factory, request_factory, tmp_path
):
    (tmp_path / "AGENTS.md").write_text("Use uv for all Python commands.")
    backend = backend_factory()
    request = request_factory()
    outcome = await backend.run(request, no_events)
    assert outcome.state == "completed"
    assert outcome.text == "Synthetic Claude public reply"
    assert outcome.native_session_ref == request.lead.conversation_id
    launch = records(tmp_path)[0]
    args = launch["argv"]
    assert args[0] == "-p"
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--model") + 1] == "model-a"
    assert args[args.index("--session-id") + 1] == request.lead.conversation_id
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert set(args[args.index("--tools") + 1].split(",")) == {"Read", "Grep", "Glob"}
    allowed = args[args.index("--allowedTools") + 1]
    assert "mcp__room__send_room_message" in allowed
    assert launch["mcp_config"].find("department_studio.bridge_mcp") >= 0
    assert "${DEPARTMENT_STUDIO_BRIDGE_TOKEN}" in launch["mcp_config"]
    assert not launch["bridge_token_literal"]
    assert launch["bridge_url_env"] == request.bridge_url
    assert launch["bridge_token_env"] == request.bridge_token
    assert launch["anthropic_base_url"] == "https://models.example.invalid/anthropic"
    assert launch["config_dir"].endswith(request.lead.id + "/claude")
    assert launch["instructions"].find("Use uv for all Python commands.") >= 0
    assert request.lead.role in launch["instructions"]
    assert not launch["owner_present"]
    prompt = next(item for item in records(tmp_path) if item.get("checkpoint") == "prompt")
    assert prompt["prompt"] == request.prompt
    assert request.prompt not in args
    await backend.close()


async def test_resume_uses_native_session_ref_and_develop_tools(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory()
    first = request_factory()
    outcome = await backend.run(first, no_events)
    resumed = replace(
        first,
        id="run-2",
        lead=replace(first.lead, permission="develop"),
        native_session_ref=outcome.native_session_ref,
    )
    assert (await backend.run(resumed, no_events)).state == "completed"
    launches = [item for item in records(tmp_path) if "argv" in item]
    assert len(launches) == 2
    assert launches[0]["resume"] is None
    assert launches[1]["resume"] == outcome.native_session_ref
    assert "--session-id" not in launches[1]["argv"]
    tools = set(launches[1]["tools"].split(","))
    assert {"Read", "Edit", "Write", "Bash"} <= tools
    await backend.close()


async def test_bridge_failure_sends_no_prompt_and_is_actionable(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("bridge_error")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "bridge" in outcome.error.lower()
    assert not any(item.get("checkpoint") == "prompt" for item in records(tmp_path))
    await backend.close()


async def test_runtime_error_is_sanitized(backend_factory, request_factory, tmp_path):
    backend = backend_factory("error")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "secret provider" not in (outcome.error or "")
    assert "Claude Code failed" in (outcome.error or "")
    await backend.close()


async def test_cancel_confirms_process_exit(backend_factory, request_factory, tmp_path):
    backend = backend_factory("hang")
    request = request_factory()
    task = asyncio.create_task(backend.run(request, no_events))
    await until(lambda: any(item.get("checkpoint") == "prompt" for item in records(tmp_path)))
    assert await backend.cancel(request.id) is True
    outcome = await task
    assert outcome.state == "interrupted"
    assert not backend._runs and not backend._clients
    await backend.close()


async def test_unknown_model_fails_before_spawning(backend_factory, request_factory, tmp_path):
    backend = backend_factory()
    request = request_factory()
    request = replace(request, lead=replace(request.lead, model_id="not-configured"))
    outcome = await backend.run(request, no_events)
    assert outcome.state == "failed"
    assert "not configured" in (outcome.error or "")
    assert not records(tmp_path)
    await backend.close()


async def test_bridge_token_is_redacted_from_public_text(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("token_echo")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "completed"
    assert "synthetic-runtime-credential" not in outcome.text
    assert "[redacted runtime credential]" in outcome.text
    await backend.close()
