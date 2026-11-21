"""Validated loopback settings and exclusive ownership of local application data."""

import ipaddress
import math
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock, Timeout


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = field(default_factory=lambda: Path(".department-studio"))
    pi_executable: str = "pi"
    claude_executable: str = "claude"
    deepseek_executable: str = "dsh"
    deepseek_profile: str = "headless"
    models_config: Path | None = None
    max_concurrency: int = 2
    max_chain_deliveries: int = 8
    run_timeout_seconds: float = 300
    stop_timeout_seconds: float = 10

    def __post_init__(self):
        try:
            if not ipaddress.ip_address(self.host).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError("The host must be a loopback IP address.") from exc
        for name in ("port", "max_concurrency", "max_chain_deliveries"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if self.port > 65535:
            raise ValueError("port must be between 1 and 65535.")
        for name in ("run_timeout_seconds", "stop_timeout_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number.")
        for name in ("pi_executable", "claude_executable", "deepseek_executable"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must name an installed executable or path.")
            resolved = shutil.which(value.strip())
            if resolved:
                object.__setattr__(self, name, str(Path(resolved).resolve()))
            else:
                object.__setattr__(self, name, value.strip())
        if not isinstance(self.deepseek_profile, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", self.deepseek_profile
        ):
            raise ValueError("deepseek_profile must be a lowercase profile name.")
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())
        models_config = self.models_config
        if models_config is None:
            models_config = os.environ.get("DEPARTMENT_STUDIO_MODELS_CONFIG")
        if models_config is not None:
            object.__setattr__(self, "models_config", Path(models_config).expanduser().resolve())

    def runtime_command(self, kind: str) -> str | None:
        """Resolve one runtime executable without making every runtime mandatory."""
        value = {
            "pi": self.pi_executable,
            "claude": self.claude_executable,
            "deepseek": self.deepseek_executable,
        }.get(kind)
        if not value:
            return None
        found = shutil.which(value)
        if found:
            return str(Path(found).resolve())
        path = Path(value).expanduser()
        return str(path.resolve()) if path.is_file() else None

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


class DataDirectory:
    """Hold this context for the entire service lifetime, before opening SQLite."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.lock = FileLock(self.path / "studio.lock", timeout=0, mode=0o600)

    def __enter__(self):
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.chmod(0o700)
        try:
            self.lock.acquire()
        except Timeout as exc:
            raise RuntimeError("This Department Studio data directory is already in use.") from exc
        try:
            sessions = self.path / "sessions"
            sessions.mkdir(exist_ok=True, mode=0o700)
            sessions.chmod(0o700)
        except BaseException:
            self.lock.release()
            raise
        return self

    def __exit__(self, *_):
        self.lock.release()
