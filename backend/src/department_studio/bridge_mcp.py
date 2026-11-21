"""Minimal MCP stdio server exposing the room message tool to non-Pi runtimes.

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
MAX_RESPONSE = 65536
TIMEOUT = 15

TOOL = {
    "name": "send_room_message",
    "description": (
        "Store a public room message. Optional explicit recipient handles request peer "
        "replies within the originating human request. No recipients means public "
        "information only. An acknowledgement confirms storage, not completion. "
        "Never include private reasoning or secrets."
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


def _post(text: str, recipients: list[str], call_id: str) -> dict:
    host, token, path, port = _credentials()
    body = json.dumps(
        {"call_id": call_id, "text": text, "recipients": recipients},
        ensure_ascii=False,
    ).encode("utf-8")
    connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE + 1)
        status = response.status
    except (OSError, http.client.HTTPException) as exc:
        raise BridgeError("Room post failed; no acknowledgement was received.") from exc
    finally:
        connection.close()
    if status != 200:
        raise BridgeError(f"Room post failed (HTTP {status}). No acknowledgement was received.")
    if len(payload) > MAX_RESPONSE:
        raise BridgeError("Room returned an oversized acknowledgement.")
    try:
        receipt = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Room returned an invalid acknowledgement.") from exc
    if (
        not isinstance(receipt, dict)
        or not isinstance(receipt.get("message_id"), str)
        or not isinstance(receipt.get("recipient_ids"), list)
        or not all(isinstance(item, str) for item in receipt["recipient_ids"])
        or (receipt.get("notice") is not None and not isinstance(receipt["notice"], str))
    ):
        raise BridgeError("Room returned an invalid acknowledgement.")
    return receipt


def _tool_call(request_id, params) -> dict:
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
    receipt = _post(text, recipients, call_id)
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
        return _response(request_id, {"tools": [TOOL]})
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
