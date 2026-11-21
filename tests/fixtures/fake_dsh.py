"""Synthetic DeepSeek Harness headless fixture. Never calls a model."""

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

MODE = os.environ.get("FAKE_DSH_MODE", "normal")
TRACE = os.environ.get("FAKE_DSH_TRACE")
LOCK = threading.Lock()


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


def stop(*_):
    trace({"checkpoint": "terminated"})
    raise SystemExit(143)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def main():
    prompt = sys.stdin.read()
    patch_path = option("--patch")
    patch = Path(patch_path).read_text() if patch_path and Path(patch_path).is_file() else ""
    trace(
        {
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
            "profile": option("--profile"),
            "json": "--json" in sys.argv,
            "session_id": option("--session-id"),
            "patch": patch,
            "prompt": prompt,
            "api_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "base_url": os.environ.get("DEEPSEEK_BASE_URL"),
            "permission_mode": os.environ.get("DSH_PERMISSION_MODE"),
            "bridge_url_env": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_URL"),
            "bridge_token_env": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN"),
            "owner_present": "DEPARTMENT_STUDIO_OWNER_TOKEN" in os.environ,
        }
    )
    session = option("--session-id") or "session-fixture-new"
    emit({"type": "session", "sessionId": session, "cwd": os.getcwd()})
    trace({"checkpoint": "session"})
    if MODE == "hang":
        while True:
            time.sleep(1)
    if MODE == "error":
        emit({"type": "error", "message": "secret provider failure"})
        return 1
    if MODE == "fail_after_final":
        emit({"type": "final", "text": "Synthetic DSH public reply"})
        return 1
    text = "Synthetic DSH public reply"
    if MODE == "token_echo":
        text += " " + os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN", "")
    emit({"type": "final", "text": text})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
