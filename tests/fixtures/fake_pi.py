"""Synthetic Pi protocol fixture. Run exclusively through the project's uv interpreter."""

import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

MODE = os.environ.get("FAKE_PI_MODE", "normal")
TRACE = os.environ.get("FAKE_PI_TRACE")
LOCK = threading.Lock()


def option(name, default=""):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def trace(record):
    if TRACE:
        with LOCK, Path(TRACE).open("a") as stream:
            stream.write(json.dumps(record) + "\n")


def emit(record, *, split=False):
    data = (json.dumps(record, ensure_ascii=False) + "\r\n").encode()
    with LOCK:
        if split:
            for byte in data:
                os.write(1, bytes([byte]))
        else:
            os.write(1, data)


def reply(command, data=None, *, success=True):
    emit(
        {
            "type": "response",
            "id": command["id"],
            "command": command["type"],
            "success": success,
            "data": data,
            "error": "Authorization: Bearer should-never-leak" if not success else None,
        }
    )


def final(text="Synthetic public reply", reason="stop", *, aborted=False):
    emit(
        {
            "type": "message_end",
            "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "private tool output"}],
            },
        }
    )
    emit(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": reason,
                "errorMessage": "secret provider error" if reason == "error" else None,
                "content": [
                    {"type": "thinking", "thinking": "private reasoning"},
                    {"type": "text", "text": text},
                ],
            },
        }
    )
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    trace({"checkpoint": "agent_end"})
    if MODE == "delayed":
        time.sleep(0.2)
    emit({"type": "agent_settled", "aborted": aborted})


def bridge():
    body = json.dumps(
        {"call_id": "fixture-call", "text": "Synthetic peer request", "recipients": ["canvas"]}
    ).encode()
    request = Request(
        os.environ["DEPARTMENT_STUDIO_BRIDGE_URL"],
        data=body,
        headers={
            "Authorization": "Bearer " + os.environ["DEPARTMENT_STUDIO_BRIDGE_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=3) as response:
        trace({"bridge_status": response.status})


trace(
    {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "bridge_token": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN"),
        "owner_present": "DEPARTMENT_STUDIO_OWNER_TOKEN" in os.environ,
        "extension_digest": hashlib.sha256(Path(option("-e")).read_bytes()).hexdigest()
        if "-e" in sys.argv
        else None,
    }
)
if MODE == "startup_exit":
    sys.exit(12)
if MODE == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if MODE == "slow_start":
    time.sleep(1.2)
if "-e" in sys.argv and MODE != "missing_bridge":
    emit(
        {
            "type": "extension_ui_request",
            "id": "bridge-ready",
            "method": "notify",
            "message": "department-studio-bridge-ready-v1",
            "notifyType": "info",
        }
    )

for line in sys.stdin:
    command = json.loads(line)
    trace(command)
    kind = command["type"]
    if kind == "echo":
        emit({"type": "response", "id": "wrong-id", "command": "echo", "success": True})
        emit(
            {
                "type": "response",
                "id": command["id"],
                "command": "echo",
                "success": True,
                "data": {"text": "星图\u2028line\u2029paragraph"},
            },
            split=True,
        )
    elif kind == "malformed":
        os.write(1, b"not-json\n")
    elif kind == "eof":
        sys.exit(0)
    elif kind == "stderr":
        os.write(2, b"secret stderr content " * 10000)
        reply(command, {"drained": True})
    elif kind == "reject":
        reply(command, success=False)
    elif kind == "never":
        pass
    elif kind == "get_state":
        reply(
            command,
            {
                "model": {
                    "provider": option("--provider", "test"),
                    "id": "wrong-model" if MODE == "wrong_model" else option("--model", "model-a"),
                },
                "sessionId": option("--session-id"),
                "sessionFile": str(Path(option("--session-dir", "/tmp")) / "fixture.jsonl"),
                "isStreaming": False,
                "isCompacting": False,
                "pendingMessageCount": 0,
            },
        )
    elif kind == "get_available_models":
        reply(
            command,
            {
                "models": [
                    {
                        "provider": "test",
                        "id": "model-a",
                        "name": "Synthetic A",
                        "headers": {"Authorization": "secret"},
                        "apiKey": "secret",
                    }
                ]
            },
        )
    elif kind == "prompt":
        if MODE == "reject":
            reply(command, success=False)
            continue
        disposition = (
            "handled" if MODE == "handled" else "queued" if MODE == "queued" else "started"
        )
        reply(command, {"disposition": disposition})
        if MODE in ("handled", "queued"):
            continue
        emit({"type": "agent_start"})
        if MODE in ("hang", "stubborn"):
            continue
        if MODE == "dialog":
            emit(
                {
                    "type": "extension_ui_request",
                    "id": "dialog-1",
                    "method": "confirm",
                    "title": "Private dialog",
                }
            )
            continue
        if MODE == "bridge" and option("--model") == "model-a":
            bridge()
        final(reason="error" if MODE == "provider_error" else "stop")
    elif kind == "extension_ui_response":
        final()
    elif kind == "clear_queue":
        if MODE != "stubborn":
            reply(command, {"steering": [], "followUp": ["queued text"]})
    elif kind == "abort":
        if MODE != "stubborn":
            time.sleep(0.05)
            emit({"type": "agent_settled", "aborted": True})
            reply(command)
    else:
        reply(command)

if MODE == "stubborn":
    while True:
        time.sleep(1)
