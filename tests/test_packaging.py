import asyncio
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import zipfile
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from department_studio.cli import parser


def test_cli_defaults_and_explicit_local_options():
    args = parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    args = parser().parse_args(["--data-dir", "/tmp/studio-test", "--pi-executable", "/bin/true"])
    assert args.pi_executable == "/bin/true"


def test_extension_is_packaged_independently_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert files("department_studio").joinpath("pi_extension.ts").is_file()


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    directory = tmp_path_factory.mktemp("wheel")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(directory)],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return next(directory.glob("*.whl"))


def artifact_environment():
    # Tests may intentionally import a review worktree through PYTHONPATH. Never
    # let that (or a developer interpreter) shadow the installed artifact in children.
    excluded = {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    return {key: value for key, value in os.environ.items() if key not in excluded} | {
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }


def wheel_command(wheel, executable="department-studio"):
    # Reuse the uv-managed interpreter version, not its site-packages. Otherwise
    # uv may choose a different locally installed Python with no cached wheels.
    return [
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--python",
        sys.executable,
        "--with",
        str(wheel),
        executable,
    ]


def test_installed_artifact_imports_and_assets_ignore_source_pythonpath(
    built_wheel, tmp_path, monkeypatch
):
    shadow = tmp_path / "shadow" / "department_studio"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise RuntimeError('source checkout was imported')")
    monkeypatch.setenv("PYTHONPATH", str(shadow.parent))
    result = subprocess.run(
        [
            *wheel_command(built_wheel, "python"),
            "-c",
            """
import hashlib, json, sys
from importlib.metadata import distribution
from pathlib import Path
from department_studio import api, domain, store, task_api, tasks
package = Path(api.__file__).resolve().parent
installed = distribution('department-studio')
assert package == Path(installed.locate_file('department_studio')).resolve()
assert json.loads(installed.read_text('direct_url.json'))['url'] == Path(sys.argv[1]).as_uri()
paths = [Path(module.__file__).resolve() for module in (api, domain, store, task_api, tasks)]
paths += [package / 'static' / name for name in ('index.html', 'app.js', 'tasks.js', 'style.css')]
assert all(path.is_relative_to(package) for path in paths)
assert 'site-packages' in package.parts
print(json.dumps({str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in paths}))
""",
            str(built_wheel),
        ],
        cwd=tmp_path,
        env=artifact_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    with zipfile.ZipFile(built_wheel) as archive:
        assert json.loads(result.stdout) == {
            name: hashlib.sha256(archive.read(f"department_studio/{name}")).hexdigest()
            for name in (
                "api.py",
                "domain.py",
                "store.py",
                "task_api.py",
                "tasks.py",
                "static/index.html",
                "static/app.js",
                "static/tasks.js",
                "static/style.css",
            )
        }


def test_built_wheel_contains_ui_bridge_and_a_working_cli(built_wheel, tmp_path):
    with zipfile.ZipFile(built_wheel) as archive:
        assert {
            "department_studio/static/index.html",
            "department_studio/static/app.js",
            "department_studio/static/tasks.js",
            "department_studio/static/style.css",
            "department_studio/pi_extension.ts",
            "department_studio/default_models.toml",
            "department_studio/models.py",
            "department_studio/instructions.py",
            "department_studio/bridge_mcp.py",
            "department_studio/backends/claude.py",
            "department_studio/backends/deepseek.py",
            "department_studio/backends/process.py",
            "department_studio/backends/registry.py",
        } <= set(archive.namelist())
    help_result = subprocess.run(
        [*wheel_command(built_wheel), "--help"],
        cwd=tmp_path,
        env=artifact_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--pi-executable" in help_result.stdout and "--data-dir" in help_result.stdout
    assert "--claude-executable" in help_result.stdout
    assert "--deepseek-executable" in help_result.stdout
    assert "--models-config" in help_result.stdout


async def test_wheel_cli_serves_authenticated_room_outside_repository(built_wheel, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        *wheel_command(built_wheel),
        "--pi-executable",
        "/bin/true",
        "--port",
        str(port),
        "--data-dir",
        str(tmp_path / "data"),
        cwd=tmp_path,
        env=artifact_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(20):
            launch = (await process.stdout.readline()).decode().strip()
            assert launch.startswith("Open Department Studio: ")
            url = urlsplit(launch.removeprefix("Open Department Studio: "))
            owner = parse_qs(url.fragment)["token"][0]
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                assert (await client.get("/api/state")).status_code == 401
                state = await client.get("/api/state", headers={"Authorization": "Bearer " + owner})
                assert state.json() == {
                    "paused": True,
                    "preparing": False,
                    "context_checks": [],
                    "leads": [],
                    "messages": [],
                    "deliveries": [],
                }
                headers = {"Authorization": "Bearer " + owner}
                assert (await client.get("/api/tasks", headers=headers)).json() == {
                    "tasks": [],
                    "next_cursor": None,
                    "open_count": 0,
                }
                assert (await client.get("/api/action-requests", headers=headers)).json() == {
                    "action_requests": [],
                    "next_cursor": None,
                }
                page = await client.get("/")
                assert page.status_code == 200 and "Department Studio" in page.text
                app_js = await client.get("/app.js")
                assert app_js.status_code == 200 and '"./tasks.js"' in app_js.text
                tasks_js = await client.get("/tasks.js")
                assert tasks_js.status_code == 200
                assert tasks_js.headers["content-type"].startswith("text/javascript")
                assert (await client.get("/style.css")).status_code == 200
                with zipfile.ZipFile(built_wheel) as archive:
                    for url, name in (
                        ("/", "index.html"),
                        ("/app.js", "app.js"),
                        ("/tasks.js", "tasks.js"),
                        ("/style.css", "style.css"),
                    ):
                        assert (await client.get(url)).content == archive.read(
                            f"department_studio/static/{name}"
                        )
                assert owner not in page.text
    finally:
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.communicate(), 5)
        except TimeoutError:
            os.killpg(process.pid, signal.SIGKILL)
            await process.communicate()
            pytest.fail("Wheel CLI did not shut down within five seconds.")


def test_cli_rejects_unavailable_port_without_emitting_launch_token(built_wheel, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = subprocess.run(
            [
                *wheel_command(built_wheel),
                "--pi-executable",
                "/bin/true",
                "--port",
                str(listener.getsockname()[1]),
                "--data-dir",
                str(tmp_path / "data"),
            ],
            cwd=tmp_path,
            env=artifact_environment(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "port unavailable" in result.stderr
        assert "token=" not in result.stdout
