"""Test-only HTTP server. Its synthetic replies never invoke a real model."""

import argparse
import json
import tempfile
from pathlib import Path

import uvicorn

from department_studio.api import create_app
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.fakes import AutomaticBackend, ControlledBackend


class BrowserBackend(AutomaticBackend):
    async def run(self, request, emit):
        data = json.loads(request.prompt.split("\n", 1)[1])
        if "synthetic wait" in data["input"]["text"]:
            return await ControlledBackend.run(self, request, emit)
        return await super().run(request, emit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="studio-browser-") as directory:
        app = create_app(
            Settings(
                port=args.port,
                data_dir=Path(directory),
                pi_executable="/bin/true",
                stop_timeout_seconds=0.5,
            ),
            backend=BrowserBackend(),
            catalog=TEST_CATALOG,
            owner_token="browser-test-owner",
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
