"""Test-only HTTP server. Its synthetic replies never invoke a real model."""

import argparse
import json
import re
import tempfile
from pathlib import Path

import httpx
import uvicorn

from department_studio.api import create_app
from department_studio.backends.base import RunOutcome
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.fakes import AutomaticBackend, ControlledBackend


class BrowserBackend(AutomaticBackend):
    async def run(self, request, emit):
        data = json.loads(request.prompt.split("\n", 1)[1])
        text = data["input"]["text"]
        if "synthetic wait" in text:
            return await ControlledBackend.run(self, request, emit)
        match = re.search(r"synthetic peer to ([a-zA-Z][a-zA-Z0-9_-]*)", text)
        if match:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    request.bridge_url,
                    headers={"Authorization": "Bearer " + request.bridge_token},
                    json={
                        "call_id": f"browser-peer-{request.id}",
                        "text": "Synthetic peer request",
                        "recipients": [match.group(1)],
                    },
                    timeout=10,
                )
                response.raise_for_status()
            return RunOutcome("completed", text="Synthetic peer request sent.")
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
            backend_factory=BrowserBackend,
            catalog=TEST_CATALOG,
            owner_token="browser-test-owner",
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
