import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from department_studio.backends.base import RunRequest
from department_studio.backends.deepseek import DeepSeekBackend
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.factories import create_lead
from tests.fakes import until

FAKE = [sys.executable, str(Path(__file__).with_name("fixtures").joinpath("fake_dsh.py"))]


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
        return DeepSeekBackend(
            Settings(deepseek_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.6),
            TEST_CATALOG,
            command_prefix=FAKE,
            extra_env={"FAKE_DSH_MODE": mode, "FAKE_DSH_TRACE": str(tmp_path / "trace.jsonl")},
        )

    return factory


def records(tmp_path):
    path = tmp_path / "trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def no_events(event):
    pass


async def test_headless_patch_selects_model_bridge_and_discuss_tools(
    backend_factory, request_factory, tmp_path
):
    (tmp_path / "AGENTS.md").write_text(
        "Use uv for all Python commands. Literal {{template}} stays literal."
    )
    backend = backend_factory()
    request = request_factory()
    outcome = await backend.run(request, no_events)
    assert outcome.state == "completed"
    assert outcome.text == "Synthetic DSH public reply"
    assert outcome.native_session_ref == "session-fixture-new"
    launch = records(tmp_path)[0]
    args = launch["argv"]
    assert args[args.index("--profile") + 1] == "headless"
    assert "--patch" in args
    assert "--json" in args
    assert args[-1] == "-"
    assert "--session-id" not in args
    assert launch["profile"] == "headless"
    assert launch["json"] is True
    assert launch["permission_mode"] == "read-only"
    assert launch["bridge_url_env"] == request.bridge_url
    assert launch["bridge_token_env"] == request.bridge_token
    assert not launch["owner_present"]
    assert launch["prompt"] == request.prompt
    patch = launch["patch"]
    assert 'provider: "deepseek-official"' in patch
    assert 'model: "model-a"' in patch
    assert "Use uv for all Python commands." in patch
    assert "{ {template} }" in patch
    assert "Keep room messages brief" in patch
    assert str(tmp_path / "records") in patch
    assert "department_studio.bridge_mcp" in patch
    assert "!!js process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN" in patch
    assert "synthetic-runtime-credential" not in patch
    assert "tool-bash" in patch and "disabled: true" in patch
    assert "write: false" in patch and "edit: false" in patch
    await backend.close()


async def test_resume_keeps_discuss_restrictions(backend_factory, request_factory, tmp_path):
    backend = backend_factory()
    first = request_factory()
    outcome = await backend.run(first, no_events)
    resumed = replace(
        first,
        id="run-2",
        native_session_ref=outcome.native_session_ref,
    )
    assert (await backend.run(resumed, no_events)).state == "completed"
    launches = [item for item in records(tmp_path) if "argv" in item]
    assert len(launches) == 2
    assert "--session-id" not in launches[0]["argv"]
    assert launches[1]["argv"][launches[1]["argv"].index("--session-id") + 1] == (
        outcome.native_session_ref
    )
    assert launches[1]["permission_mode"] == "read-only"
    assert "tool-bash" in launches[1]["patch"]
    await backend.close()


async def test_final_with_nonzero_exit_is_a_failure(backend_factory, request_factory, tmp_path):
    backend = backend_factory("fail_after_final")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "DeepSeek Harness failed" in (outcome.error or "")
    await backend.close()


async def test_error_event_is_sanitized(backend_factory, request_factory, tmp_path):
    backend = backend_factory("error")
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "secret provider" not in (outcome.error or "")
    await backend.close()


async def test_cancel_confirms_process_exit(backend_factory, request_factory, tmp_path):
    backend = backend_factory("hang")
    request = request_factory()
    task = asyncio.create_task(backend.run(request, no_events))
    await until(
        lambda: (
            any(item.get("type") == "session" for item in records(tmp_path))
            or any(item.get("checkpoint") == "session" for item in records(tmp_path))
        )
    )
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
