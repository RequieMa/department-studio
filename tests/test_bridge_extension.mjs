import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import { after, before, test } from "node:test";
import register from "../backend/src/department_studio/pi_extension.ts";

let server;
let url;
const received = [];

before(async () => {
  server = http.createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    const data = body ? JSON.parse(body) : null;
    received.push({ method: request.method, path: request.url, headers: request.headers, data });
    response.setHeader("Content-Type", "application/json");
    if (request.method === "GET" && request.url === "/api/bridge/records") {
      response.end(JSON.stringify({ records: [{ name: "audit.md", size: 12, modified: "now" }] }));
      return;
    }
    if (request.method === "GET" && request.url.startsWith("/api/bridge/records/")) {
      response.end(JSON.stringify({
        name: "audit.md", path: "/project/records/audit.md", content: "# Durable evidence", size: 20,
      }));
      return;
    }
    if (request.method === "POST" && request.url === "/api/bridge/records") {
      response.end(JSON.stringify({
        name: data.name, path: `/project/records/${data.name}`, size: data.content.length,
      }));
      return;
    }
    if (data?.text === "wait") return;
    if (data?.text === "fail") {
      response.writeHead(409).end(JSON.stringify({ detail: "do not echo private server payload" }));
    } else {
      response.end(JSON.stringify({ message_id: "message-1", recipient_ids: ["lead-2"], notice: null }));
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  url = `http://127.0.0.1:${server.address().port}/api/bridge/messages`;
});

after(() => {
  server.closeAllConnections();
  server.close();
  delete process.env.DEPARTMENT_STUDIO_BRIDGE_URL;
  delete process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN;
});

function registeredTools() {
  process.env.DEPARTMENT_STUDIO_BRIDGE_URL = url;
  process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN = "first-generation-token";
  const tools = {};
  register({ registerTool(definition) { tools[definition.name] = definition; }, on() {} });
  return tools;
}

function tool() {
  return registeredTools().send_room_message;
}

test("tool arguments contain no sender, actor, generation or credentials", () => {
  const definition = tool();
  assert.equal(definition.name, "send_room_message");
  assert.deepEqual(Object.keys(definition.parameters.properties).sort(), ["recipients", "text"]);
  assert.equal(definition.parameters.additionalProperties, false);
});

test("posts only explicit arguments with immutable token and tool-derived call ID", async () => {
  const definition = tool();
  process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN = "later-generation-token";
  const result = await definition.execute("native-call-1", {
    text: "Review this", recipients: ["canvas"], sender: "human", call_id: "forged",
  });
  const request = received.at(-1);
  assert.equal(request.headers.authorization, "Bearer first-generation-token");
  assert.deepEqual(request.data, { call_id: "native-call-1", text: "Review this", recipients: ["canvas"] });
  assert.deepEqual(result.details, { message_id: "message-1", recipient_ids: ["lead-2"], notice: null });
  assert.match(result.content[0].text, /stored/i);
  await definition.execute("native-call-1", { text: "Review this", recipients: ["canvas"] });
  assert.equal(received.at(-1).data.call_id, request.data.call_id);
});

test("non-2xx responses are failures with no raw response body", async () => {
  await assert.rejects(tool().execute("error-call", { text: "fail" }), (error) => {
    assert.match(error.message, /409/);
    assert.doesNotMatch(error.message, /private server payload/);
    return true;
  });
});

test("cancellation aborts an in-flight HTTP callback", async () => {
  const controller = new AbortController();
  const request = tool().execute("canceled-call", { text: "wait" }, controller.signal);
  setTimeout(() => controller.abort(), 20);
  await assert.rejects(request, (error) => error.name === "AbortError");
});

test("runtime endpoint must be the loopback bridge path", () => {
  process.env.DEPARTMENT_STUDIO_BRIDGE_URL = "https://example.com/api/bridge/messages";
  assert.throws(() => register({ registerTool() {} }), /loopback/);
});

test("signals successful registration before any model prompt", () => {
  process.env.DEPARTMENT_STUDIO_BRIDGE_URL = url;
  const hooks = new Map();
  const notices = [];
  register({ registerTool() {}, on(name, handler) { hooks.set(name, handler); } });
  assert.equal(typeof hooks.get("session_start"), "function");
  hooks.get("session_start")({}, { ui: { notify(message) { notices.push(message); } } });
  assert.deepEqual(notices, ["department-studio-bridge-ready-v1"]);
});


test("records tools are registered and write/read/list through the bridge", async () => {
  const tools = registeredTools();
  assert.deepEqual(
    Object.keys(tools).sort(),
    ["list_records", "read_record", "send_room_message", "write_record"],
  );
  const written = await tools.write_record.execute("record-call", {
    name: "audit.md", content: "More evidence", mode: "append",
  });
  const write = received.at(-1);
  assert.equal(write.path, "/api/bridge/records");
  assert.equal(write.headers.authorization, "Bearer first-generation-token");
  assert.deepEqual(write.data, { name: "audit.md", content: "More evidence", mode: "append" });
  assert.match(written.content[0].text, /Record saved/);

  const read = await tools.read_record.execute("record-read", { name: "audit.md" });
  assert.equal(received.at(-1).method, "GET");
  assert.equal(received.at(-1).path, "/api/bridge/records/audit.md");
  assert.match(read.content[0].text, /Durable evidence/);

  const listed = await tools.list_records.execute("record-list", {});
  assert.equal(received.at(-1).path, "/api/bridge/records");
  assert.match(listed.content[0].text, /audit\.md/);
});
