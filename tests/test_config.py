import os
import shutil
import stat
from pathlib import Path

import pytest

from department_studio.config import DataDirectory, Settings


def test_defaults_are_loopback_and_bounded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(pi_executable="/bin/true")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.origin == "http://127.0.0.1:8765"
    assert settings.data_dir == tmp_path / ".department-studio"
    assert settings.pi_executable == str(Path("/bin/true").resolve())
    assert settings.max_concurrency == 2
    assert settings.max_chain_deliveries == 8
    assert settings.run_timeout_seconds == 300
    assert settings.stop_timeout_seconds == 10


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.1", "example.com", "::"])
def test_non_loopback_rejected(host):
    with pytest.raises(ValueError, match="loopback"):
        Settings(host=host, pi_executable="/bin/true")


@pytest.mark.parametrize(
    "field,value",
    [
        ("port", 0),
        ("port", 65536),
        ("port", True),
        ("port", 2.5),
        ("max_concurrency", 0),
        ("max_concurrency", False),
        ("max_chain_deliveries", -1),
        ("run_timeout_seconds", 0),
        ("run_timeout_seconds", float("nan")),
        ("stop_timeout_seconds", float("inf")),
        ("stop_timeout_seconds", -1),
    ],
)
def test_invalid_numeric_settings(field, value):
    with pytest.raises(ValueError):
        Settings(pi_executable="/bin/true", **{field: value})


def test_ipv6_origin():
    assert Settings(host="::1", pi_executable="/bin/true").origin == "http://[::1]:8765"


def test_missing_runtime_does_not_block_other_runtimes():
    settings = Settings(pi_executable="/missing/department-studio-pi")
    assert settings.runtime_command("pi") is None
    assert settings.runtime_command("claude") == shutil.which(settings.claude_executable)
    assert settings.runtime_command("deepseek") == shutil.which(settings.deepseek_executable)


def test_runtime_specific_settings_and_catalog_path(tmp_path):
    catalog = tmp_path / "models.toml"
    settings = Settings(
        pi_executable="/bin/true",
        claude_executable="/bin/false",
        deepseek_executable="/bin/true",
        deepseek_profile="review",
        models_config=catalog,
    )
    assert settings.claude_executable == str(Path("/bin/false").resolve())
    assert settings.deepseek_profile == "review"
    assert settings.models_config == catalog.resolve()
    with pytest.raises(ValueError, match="deepseek_profile"):
        Settings(pi_executable="/bin/true", deepseek_profile="Bad Profile")


def test_executable_resolves_from_path(tmp_path, monkeypatch):
    executable = tmp_path / "test-pi"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert Settings(pi_executable="test-pi").pi_executable == str(executable)


def test_private_directory_and_exclusive_lock(tmp_path):
    data = tmp_path / "local"
    with DataDirectory(data):
        assert stat.S_IMODE(data.stat().st_mode) == 0o700
        assert (data / "sessions").is_dir()
        assert stat.S_IMODE((data / "sessions").stat().st_mode) == 0o700
        with pytest.raises(RuntimeError, match="already in use"):
            with DataDirectory(data):
                pytest.fail("Two services acquired the same directory")
    with DataDirectory(data):
        assert os.access(data, os.W_OK)


def test_models_config_environment_fallback(tmp_path, monkeypatch):
    path = tmp_path / "catalog.toml"
    monkeypatch.setenv("DEPARTMENT_STUDIO_MODELS_CONFIG", str(path))
    assert Settings(pi_executable="/bin/true").models_config == path.resolve()
