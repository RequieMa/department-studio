import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.server.requests.append(
            {"method": "GET", "path": self.path, "authorization": self.headers.get("Authorization")}
        )
        if self.server.fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"secret upstream body")
            return
        if self.path == "/api/bridge/records":
            self._json(200, {"records": self.server.records})
        elif self.path.startswith("/api/bridge/records/"):
            name = self.path.rsplit("/", 1)[-1]
            self._json(
                200,
                {
                    "name": name,
                    "path": f"/project/records/{name}",
                    "content": "# Note\n\nDurable evidence.",
                    "size": 26,
                },
            )
        else:
            self._json(404, {"detail": "missing"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append(
            {
                "method": "POST",
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        if self.server.fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"secret upstream body")
            return
        if self.path == "/api/bridge/records":
            self._json(
                200,
                {"name": body["name"], "path": f"/project/records/{body['name']}", "size": 42},
            )
            return
        self._json(
            200,
            {"message_id": "message-1", "recipient_ids": ["lead-2"], "notice": None},
        )

    def log_message(self, *_):
        pass


def server(*, fail=False):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.requests = []
    instance.records = [{"name": "2026-11-21-audit.md", "size": 120, "modified": "now"}]
    instance.fail = fail
    threading.Thread(target=instance.serve_forever, daemon=True).start()
    return instance


def bridge(port, *, token="runtime-token"):
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


def test_mcp_handshake_lists_and_calls_room_message_tool():
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
        names = {tool["name"] for tool in tools["result"]["tools"]}
        assert names == {"send_room_message", "list_records", "read_record", "write_record"}
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
        message = next(item for item in http.requests if item["path"] == "/api/bridge/messages")
        assert message["authorization"] == "Bearer runtime-token"
        assert message["body"] == {
            "call_id": "mcp-3",
            "text": "Public note",
            "recipients": ["canvas"],
        }
    finally:
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        http.shutdown()


def test_mcp_records_tools_list_read_and_write():
    http = server()
    process = bridge(http.server_address[1])
    try:
        listed = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "list_records", "arguments": {}},
            },
        )
        assert "2026-11-21-audit.md" in listed["result"]["content"][0]["text"]
        read = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "read_record", "arguments": {"name": "2026-11-21-audit.md"}},
            },
        )
        assert "Durable evidence." in read["result"]["content"][0]["text"]
        written = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "write_record",
                    "arguments": {
                        "name": "2026-11-21-audit.md",
                        "content": "More evidence",
                        "mode": "append",
                    },
                },
            },
        )
        assert written["result"]["isError"] is False
        post = next(
            item
            for item in http.requests
            if item["method"] == "POST" and item["path"] == "/api/bridge/records"
        )
        assert post["body"] == {
            "name": "2026-11-21-audit.md",
            "content": "More evidence",
            "mode": "append",
        }
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
        assert not http.requests
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
