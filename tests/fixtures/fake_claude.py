"""Synthetic Claude Code stream-json fixture. Never calls a model."""

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

MODE = os.environ.get("FAKE_CLAUDE_MODE", "normal")
TRACE = os.environ.get("FAKE_CLAUDE_TRACE")
LOCK = threading.Lock()
PROMPT = ""


def option(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def trace(record):
    if TRACE:
        with LOCK, Path(TRACE).open("a") as stream:
            stream.write(json.dumps(record) + "\n")


def emit(record):
    with LOCK:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def session_id():
    return option("--resume") or option("--session-id") or "generated-claude-session"


def stop(*_):
    trace({"checkpoint": "terminated"})
    raise SystemExit(143)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def main():
    global PROMPT
    mcp_path = option("--mcp-config")
    mcp_text = Path(mcp_path).read_text() if mcp_path and Path(mcp_path).is_file() else ""
    trace(
        {
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
            "model": option("--model"),
            "resume": option("--resume"),
            "session_id": option("--session-id"),
            "tools": option("--tools"),
            "allowed": option("--allowedTools"),
            "permission": option("--permission-mode"),
            "instructions": option("--append-system-prompt"),
            "mcp_config": mcp_text,
            "bridge_token_literal": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN", "")
            in mcp_text,
            "bridge_url_env": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_URL"),
            "bridge_token_env": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN"),
            "anthropic_base_url": os.environ.get("ANTHROPIC_BASE_URL"),
            "anthropic_auth": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
            "owner_present": "DEPARTMENT_STUDIO_OWNER_TOKEN" in os.environ,
        }
    )
    if MODE == "bridge_error":
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": session_id(),
                "mcp_servers": [],
                "mcp_server_errors": [{"name": "room", "message": "no bridge"}],
            }
        )
        time.sleep(5)
        return 1
    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": session_id(),
            "mcp_servers": [{"name": "room", "status": "connected"}],
        }
    )
    trace({"checkpoint": "init"})
    PROMPT = sys.stdin.read()
    trace({"checkpoint": "prompt", "prompt": PROMPT})
    if MODE == "hang":
        while True:
            time.sleep(1)
    if MODE == "error":
        emit(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "result": "secret provider failure",
                "session_id": session_id(),
            }
        )
        return 1
    if MODE == "empty":
        emit(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "",
                "session_id": session_id(),
            }
        )
        return 0
    text = "Synthetic Claude public reply"
    if MODE == "token_echo":
        text += " " + os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN", "")
    emit(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "partial"}]},
            "session_id": session_id(),
        }
    )
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": text,
            "session_id": session_id(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
