"""Single-process loopback launcher. Never enable reload for a self-development workspace."""

import argparse
import socket
import sys
from pathlib import Path

import uvicorn

from department_studio.api import create_app
from department_studio.config import DataDirectory, Settings
from department_studio.store import Store


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Department Studio — a local, user-led room")
    result.add_argument("--host", default="127.0.0.1", help="Loopback IP address only")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--data-dir", type=Path, default=Path(".department-studio"))
    result.add_argument(
        "--pi-executable", default="pi", help="Installed Pi executable name or path"
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        settings = Settings(**vars(args))
        with (
            DataDirectory(settings.data_dir),
            Store(
                settings.data_dir / "room.sqlite",
                max_chain_deliveries=settings.max_chain_deliveries,
            ) as store,
        ):
            family = socket.AF_INET6 if ":" in settings.host else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as listener:
                try:
                    listener.bind((settings.host, settings.port))
                    listener.listen(128)
                    listener.setblocking(False)
                except OSError as exc:
                    raise RuntimeError("Local port unavailable; choose another --port.") from exc
                app = create_app(settings, store=store)
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
                return 0 if server.started and app.state.service.shutdown_confirmed else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Department Studio: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
