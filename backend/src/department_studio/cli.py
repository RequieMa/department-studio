"""Single-process loopback launcher. Never enable reload for a self-development workspace."""

import argparse
import socket
import sys
from pathlib import Path

import uvicorn

from department_studio.api import create_app
from department_studio.config import Settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Department Studio — a local, user-led room")
    result.add_argument("--host", default="127.0.0.1", help="Loopback IP address only")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--data-dir", type=Path, default=Path(".department-studio"))
    result.add_argument(
        "--pi-executable", default="pi", help="Installed Pi executable name or path"
    )
    result.add_argument(
        "--claude-executable", default="claude", help="Installed Claude Code executable"
    )
    result.add_argument(
        "--deepseek-executable", default="dsh", help="Installed DeepSeek Harness executable"
    )
    result.add_argument(
        "--deepseek-profile", default="headless", help="DeepSeek Harness profile to boot"
    )
    result.add_argument(
        "--models-config",
        type=Path,
        default=None,
        help="OpenAI-compatible model catalog TOML (default: bundled DeepSeek catalog)",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        settings = Settings(**vars(args))
        family = socket.AF_INET6 if ":" in settings.host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            try:
                listener.bind((settings.host, settings.port))
                listener.listen(128)
                listener.setblocking(False)
            except OSError as exc:
                raise RuntimeError("Local port unavailable; choose another --port.") from exc
            # No Store is injected: the app owns the project catalog and opens the
            # active project's isolated Store after the port is known to be free.
            app = create_app(settings)
            config = uvicorn.Config(
                app,
                host=settings.host,
                port=settings.port,
                workers=1,
                reload=False,
                access_log=False,
                proxy_headers=False,
                log_level="warning",
            )
            print(
                f"Open Department Studio: {settings.origin}/#token={app.state.owner.token}",
                flush=True,
            )
            print("The launch URL controls this local room. Keep it private.", flush=True)
            server = uvicorn.Server(config)
            server.run(sockets=[listener])
            service = getattr(app.state, "service", None)
            return 0 if server.started and service is not None and service.shutdown_confirmed else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Department Studio: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
