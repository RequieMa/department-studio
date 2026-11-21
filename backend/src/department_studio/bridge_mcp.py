"""Minimal MCP stdio server exposing room messages and project records.

The process receives one immutable delivery credential through its environment.
It speaks newline-delimited JSON-RPC on stdin/stdout and posts to the loopback
bridge endpoint over HTTP. No native runtime gets the browser owner credential.
"""

import http.client
import json
import os
import sys
import uuid
from urllib.parse import urlsplit

MAX_TEXT = 32000
MAX_RECIPIENTS = 8
MAX_RECORD = 524288
MAX_RESPONSE = 1048576
TIMEOUT = 15
RECORD_NAME = "^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\\.md$"

MESSAGE_TOOL = {
    "name": "send_room_message",
    "description": (
        "Store a brief public room message. Optional explicit recipient handles request "
        "peer replies within the originating human request. No recipients means public "
        "information only. Put durable details in project records and reference the file "
        "path. An acknowledgement confirms storage, not completion. Never include private "
        "reasoning or secrets."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "recipients": {
                "type": "array",
                "maxItems": MAX_RECIPIENTS,
                "items": {
                    "type": "string",
                    "pattern": "^[a-zA-Z][a-zA-Z0-9_-]{0,31}$",
                },
                "description": "Recipient handles without @. Do not address yourself or use all.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}

TOOLS = [
    {
        "name": "list_records",
        "description": (
            "List durable Markdown records for this project. Use records for audit notes; "
            "keep room messages short."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_record",
        "description": "Read one Markdown record by exact filename.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "pattern": RECORD_NAME}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_record",
        "description": (
            "Append to or replace one Markdown record in the project records folder. "
            "Reference the exact path in the room instead of pasting the content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "pattern": RECORD_NAME},
                "content": {"type": "string", "minLength": 1, "maxLength": MAX_RECORD},
                "mode": {"type": "string", "enum": ["append", "replace"], "default": "append"},
            },
            "required": ["name", "content"],
            "additionalProperties": False,
        },
    },
    MESSAGE_TOOL,
]


class BridgeError(RuntimeError):
    pass


def _credentials() -> tuple[str, str, str, int]:
    token = os.environ.get("DEPARTMENT_STUDIO_BRIDGE_TOKEN", "")
    address = os.environ.get("DEPARTMENT_STUDIO_BRIDGE_URL", "")
    if not token or len(token) > 512 or not address:
        raise BridgeError("Room bridge credentials are missing.")
    try:
        url = urlsplit(address)
        port = url.port or 80
    except ValueError as exc:
        raise BridgeError("Room bridge address is invalid.") from exc
    loopback = url.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        url.scheme != "http"
        or not loopback
        or url.path != "/api/bridge/messages"
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise BridgeError("Room bridge must use the configured loopback endpoint.")
    return url.hostname, token, url.path, port


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    host, token, message_path, port = _credentials()
    root = message_path.rsplit("/", 1)[0]
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
    try:
        connection.request(method, f"{root}{path}", body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        status = response.status
    except (OSError, http.client.HTTPException) as exc:
        raise BridgeError("Room bridge failed; no acknowledgement was received.") from exc
    finally:
        connection.close()
    if status != 200:
        raise BridgeError(f"Room bridge failed (HTTP {status}). No acknowledgement was received.")
    if len(raw) > MAX_RESPONSE:
        raise BridgeError("Room bridge returned an oversized response.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Room bridge returned an invalid response.") from exc
    if not isinstance(value, dict):
        raise BridgeError("Room bridge returned an invalid response.")
    return value


def _send_message(request_id, params) -> dict:
    if not isinstance(params, dict) or params.get("name") != "send_room_message":
        raise BridgeError("Unknown tool.")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) - {"text", "recipients"}:
        raise BridgeError("Invalid tool arguments.")
    text = arguments.get("text")
    recipients = arguments.get("recipients", [])
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise BridgeError("Tool text must contain 1–32000 characters.")
    if not isinstance(recipients, list) or len(recipients) > MAX_RECIPIENTS:
        raise BridgeError("Invalid recipient list.")
    for handle in recipients:
        if not isinstance(handle, str) or not handle or len(handle) > 32:
            raise BridgeError("Invalid recipient handle.")
    call_id = f"mcp-{request_id}" if isinstance(request_id, (str, int)) else f"mcp-{uuid.uuid4()}"
    receipt = _request(
        "POST",
        "/messages",
        {"call_id": call_id, "text": text, "recipients": recipients},
    )
    if (
        not isinstance(receipt.get("message_id"), str)
        or not isinstance(receipt.get("recipient_ids"), list)
        or not all(isinstance(item, str) for item in receipt["recipient_ids"])
        or (receipt.get("notice") is not None and not isinstance(receipt["notice"], str))
    ):
        raise BridgeError("Room returned an invalid acknowledgement.")
    details = {
        "message_id": receipt["message_id"],
        "recipient_ids": receipt["recipient_ids"],
        "notice": receipt.get("notice"),
    }
    summary = receipt.get("notice") or (
        f"{len(receipt['recipient_ids'])} recipient deliveries queued."
    )
    return {
        "content": [{"type": "text", "text": f"Message stored. {summary}"}],
        "details": details,
        "isError": False,
    }


def _record_tool(request_id, params) -> dict:
    if not isinstance(params, dict):
        raise BridgeError("Invalid tool parameters.")
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        raise BridgeError("Invalid tool arguments.")
    if name == "list_records":
        payload = _request("GET", "/records")
        records = payload.get("records")
        if not isinstance(records, list):
            raise BridgeError("Room bridge returned an invalid record list.")
        lines = [
            f"{record.get('name')} ({record.get('size')} bytes)"
            for record in records
            if isinstance(record, dict) and isinstance(record.get("name"), str)
        ]
        return {
            "content": [{"type": "text", "text": "\n".join(lines) if lines else "No records yet."}],
            "details": {"records": records},
            "isError": False,
        }
    record_name = arguments.get("name")
    if not isinstance(record_name, str) or not record_name:
        raise BridgeError("Record name is required.")
    if name == "read_record":
        payload = _request("GET", f"/records/{record_name}")
        content = payload.get("content")
        if not isinstance(content, str) or not isinstance(payload.get("path"), str):
            raise BridgeError("Room bridge returned an invalid record.")
        return {
            "content": [{"type": "text", "text": content}],
            "details": {"name": payload.get("name"), "path": payload["path"]},
            "isError": False,
        }
    if name == "write_record":
        content = arguments.get("content")
        mode = arguments.get("mode", "append")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_RECORD:
            raise BridgeError("Record content must contain text.")
        if mode not in {"append", "replace"}:
            raise BridgeError("Record mode must be append or replace.")
        payload = _request(
            "POST",
            "/records",
            {"name": record_name, "content": content, "mode": mode},
        )
        if not isinstance(payload.get("path"), str):
            raise BridgeError("Room bridge returned an invalid record.")
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Record saved: {payload['path']} ({payload.get('size')} bytes).",
                }
            ],
            "details": {
                "name": payload.get("name"),
                "path": payload["path"],
                "size": payload.get("size"),
            },
            "isError": False,
        }
    raise BridgeError("Unknown tool.")


def _tool_call(request_id, params) -> dict:
    if not isinstance(params, dict):
        raise BridgeError("Unknown tool.")
    if params.get("name") == "send_room_message":
        return _send_message(request_id, params)
    return _record_tool(request_id, params)


def _response(request_id, result=None, error=None) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return message


def handle(message) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _response(None, error={"code": -32600, "message": "Invalid Request"})
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")
    if request_id is None:
        return None  # Notification.
    if method == "initialize":
        version = (
            params.get("protocolVersion")
            if isinstance(params, dict) and isinstance(params.get("protocolVersion"), str)
            else "2024-11-05"
        )
        return _response(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "department-studio-room", "version": "1"},
            },
        )
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method in {"resources/list"}:
        return _response(request_id, {"resources": []})
    if method in {"prompts/list"}:
        return _response(request_id, {"prompts": []})
    if method == "tools/call":
        try:
            return _response(request_id, _tool_call(request_id, params))
        except BridgeError as exc:
            return _response(
                request_id,
                result={
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
    return _response(request_id, error={"code": -32601, "message": "Method not found"})


def serve() -> int:
    try:
        _credentials()
    except BridgeError as exc:
        print(f"department-studio bridge: {exc}", file=sys.stderr)
        return 1
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            response = _response(None, error={"code": -32700, "message": "Parse error"})
        else:
            response = handle(message)
        if response is None:
            continue
        try:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
