"""Validated loopback settings and exclusive ownership of local application data."""

import ipaddress
import math
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
        executable = shutil.which(str(self.pi_executable))
        if not executable:
            raise ValueError("Pi executable not found; install Pi or pass --pi-executable PATH.")
        object.__setattr__(self, "pi_executable", str(Path(executable).resolve()))
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())

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
