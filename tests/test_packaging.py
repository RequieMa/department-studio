import asyncio
import os
import signal
import socket
import subprocess
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


def wheel_command(wheel):
    return ["uv", "run", "--isolated", "--no-project", "--with", str(wheel), "department-studio"]


def test_built_wheel_contains_ui_bridge_and_a_working_cli(built_wheel, tmp_path):
    with zipfile.ZipFile(built_wheel) as archive:
        assert {
            "department_studio/static/index.html",
            "department_studio/static/app.js",
            "department_studio/static/style.css",
            "department_studio/pi_extension.ts",
        } <= set(archive.namelist())
    help_result = subprocess.run(
        [*wheel_command(built_wheel), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--pi-executable" in help_result.stdout and "--data-dir" in help_result.stdout


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
                    "leads": [],
                    "messages": [],
                    "deliveries": [],
                }
                page = await client.get("/")
                assert page.status_code == 200 and "Department Studio" in page.text
                assert (await client.get("/app.js")).status_code == 200
                assert (await client.get("/style.css")).status_code == 200
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
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "port unavailable" in result.stderr
        assert "token=" not in result.stdout
