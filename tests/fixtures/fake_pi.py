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
PENDING_PROMPT = None
COMPACTED = False


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
    if MODE == "compaction_after_success":
        emit({"type": "compaction_start", "reason": "threshold"})
        emit(
            {
                "type": "compaction_end",
                "aborted": False,
                "willRetry": False,
                "errorMessage": "Authorization: Bearer secret-compaction-error",
            }
        )
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


AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR")
MODELS_CONFIG = None
if AGENT_DIR:
    try:
        MODELS_CONFIG = json.loads((Path(AGENT_DIR) / "models.json").read_text())
    except (OSError, ValueError):
        MODELS_CONFIG = {"error": "unreadable"}
trace(
    {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "bridge_token": os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN"),
        "owner_present": "DEPARTMENT_STUDIO_OWNER_TOKEN" in os.environ,
        "agent_dir": AGENT_DIR,
        "models_config": MODELS_CONFIG,
        "model_key_present": bool(os.environ.get("DEPARTMENT_STUDIO_MODEL_API_KEY")),
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
        if MODE == "silent_state":
            continue
        reply(
            command,
            {
                "model": {
                    "provider": option("--provider", "test"),
                    "id": "wrong-model" if MODE == "wrong_model" else option("--model", "model-a"),
                    "contextWindow": 100000,
                },
                "sessionId": "wrong-session"
                if MODE == "context_wrong_session"
                else option("--session-id"),
                "sessionFile": str(Path(option("--session-dir", "/tmp")) / "fixture.jsonl"),
                "isStreaming": MODE == "context_busy",
                "isCompacting": False,
                "pendingMessageCount": 0,
                "messageCount": 0 if MODE == "context_empty" else 12,
            },
        )
    elif kind == "get_session_stats":
        tokens = 10000
        if MODE == "context_overflow":
            tokens = 210000
        elif MODE.startswith("context_") and MODE not in {"context_null_usage", "context_empty"}:
            tokens = 75000
        if COMPACTED or MODE == "context_null_usage":
            tokens = None
        reply(
            command,
            {
                "tokens": {"total": 9000000},  # Lifetime totals must not drive compaction.
                "contextUsage": {"tokens": tokens, "contextWindow": 100000},
            },
        )
    elif kind == "get_messages":
        reply(command, {"messages": [{"role": "user", "content": "A compact handoff"}]})
    elif kind == "compact":
        emit({"type": "compaction_start", "reason": "manual"})
        if MODE == "context_hang":
            continue
        if MODE == "context_failed":
            emit(
                {
                    "type": "compaction_end",
                    "errorMessage": "secret-provider-error",
                    "aborted": False,
                }
            )
            reply(command, success=False)
            continue
        COMPACTED = True
        result = {
            "summary": "Private context summary",
            "firstKeptEntryId": "retained-entry",
            "estimatedTokensAfter": 75000 if MODE == "context_ineffective" else 15000,
        }
        if MODE == "context_bad_result":
            result = {}
        emit({"type": "compaction_end", "result": result, "aborted": False})
        reply(command, result)
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
        if MODE == "silent_prompt":
            continue
        if MODE in {"compaction_before_ack", "compaction_without_ack", "compaction_failed"}:
            emit({"type": "compaction_start", "reason": "threshold"})
            trace({"checkpoint": "compaction_start"})
            if MODE == "compaction_without_ack":
                continue
            if MODE == "compaction_before_ack":
                time.sleep(0.5)
            emit(
                {
                    "type": "compaction_end",
                    "result": {"summary": "private compaction summary"}
                    if MODE == "compaction_before_ack"
                    else None,
                    "aborted": False,
                    "willRetry": False,
                    "errorMessage": "Authorization: Bearer secret-compaction-error"
                    if MODE == "compaction_failed"
                    else None,
                }
            )
        if MODE in {"finished_before_ack", "finished_without_ack"}:
            final()
            if MODE == "finished_before_ack":
                time.sleep(0.05)
                reply(command, {"disposition": "started"})
            continue
        if MODE == "dialog_before_ack":
            PENDING_PROMPT = command
            emit(
                {
                    "type": "extension_ui_request",
                    "id": "before-ack",
                    "method": "confirm",
                    "title": "Private pre-acceptance dialog",
                }
            )
            continue
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
        if MODE == "length_recovered":
            emit(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "stopReason": "length",
                        "content": [{"type": "text", "text": "incomplete private attempt"}],
                    },
                }
            )
            emit({"type": "agent_end", "messages": [], "willRetry": True})
            emit({"type": "compaction_start", "reason": "overflow"})
            emit(
                {
                    "type": "compaction_end",
                    "result": {"summary": "private compaction summary"},
                    "aborted": False,
                    "willRetry": True,
                }
            )
        reason = (
            "error"
            if MODE == "provider_error"
            else "length"
            if MODE in {"length", "compaction_failed"}
            else "stop"
        )
        final(reason=reason)
    elif kind == "extension_ui_response":
        if PENDING_PROMPT is not None:
            reply(PENDING_PROMPT, {"disposition": "started"})
            PENDING_PROMPT = None
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
