import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.server.records.append(
            {"path": self.path, "authorization": self.headers.get("Authorization"), "body": body}
        )
        if self.server.fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"secret upstream body")
            return
        receipt = {
            "message_id": "message-1",
            "recipient_ids": ["lead-2"],
            "notice": None,
        }
        payload = json.dumps(receipt).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


def server(*, fail=False):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.records = []
    instance.fail = fail
    threading.Thread(target=instance.serve_forever, daemon=True).start()
    return instance


def bridge(port, *, token="runtime-token", fail=False):
    url = f"http://127.0.0.1:{port}/api/bridge/messages"
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("DEPARTMENT_STUDIO_")
    }
    env.update(
        {
            "DEPARTMENT_STUDIO_BRIDGE_URL": url,
            "DEPARTMENT_STUDIO_BRIDGE_TOKEN": token,
        }
    )
    return subprocess.Popen(
        [sys.executable, "-m", "department_studio.bridge_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )


def send(process, message):
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def test_mcp_handshake_lists_and_calls_the_room_tool():
    http = server()
    process = bridge(http.server_address[1])
    try:
        init = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
        )
        assert init["result"]["protocolVersion"] == "2025-06-18"
        assert init["result"]["capabilities"]["tools"] == {}
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        process.stdin.flush()
        tools = send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert tools["result"]["tools"][0]["name"] == "send_room_message"
        call = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "send_room_message",
                    "arguments": {"text": "Public note", "recipients": ["canvas"]},
                },
            },
        )
        assert call["result"]["isError"] is False
        assert "Message stored." in call["result"]["content"][0]["text"]
        assert http.records == [
            {
                "path": "/api/bridge/messages",
                "authorization": "Bearer runtime-token",
                "body": {
                    "call_id": "mcp-3",
                    "text": "Public note",
                    "recipients": ["canvas"],
                },
            }
        ]
    finally:
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        http.shutdown()


def test_http_failure_is_reported_without_leaking_the_body():
    http = server(fail=True)
    process = bridge(http.server_address[1])
    try:
        response = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "send_room_message", "arguments": {"text": "Hello"}},
            },
        )
        assert response["result"]["isError"] is True
        assert "HTTP 500" in response["result"]["content"][0]["text"]
        assert "secret upstream body" not in json.dumps(response)
    finally:
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        http.shutdown()


def test_invalid_arguments_are_rejected_locally():
    http = server()
    process = bridge(http.server_address[1])
    try:
        response = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "send_room_message", "arguments": {"text": ""}},
            },
        )
        assert response["result"]["isError"] is True
        assert not http.records
    finally:
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        http.shutdown()


def test_missing_credentials_exit_without_speaking_protocol():
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("DEPARTMENT_STUDIO_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "department_studio.bridge_mcp"],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 1
    assert "credentials" in result.stderr.lower()
    assert result.stdout == ""


def test_non_loopback_bridge_address_is_refused():
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("DEPARTMENT_STUDIO_")
    }
    env.update(
        {
            "DEPARTMENT_STUDIO_BRIDGE_URL": "http://192.0.2.1/api/bridge/messages",
            "DEPARTMENT_STUDIO_BRIDGE_TOKEN": "token",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "department_studio.bridge_mcp"],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 1
    assert "loopback" in result.stderr
