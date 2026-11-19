import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import { after, before, test } from "node:test";
import register from "../src/department_studio/pi_extension.ts";

let server;
let url;
const received = [];

before(async () => {
  server = http.createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    const data = JSON.parse(body);
    received.push({ headers: request.headers, data });
    if (data.text === "wait") return;
    response.setHeader("Content-Type", "application/json");
    if (data.text === "fail") {
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

function tool() {
  process.env.DEPARTMENT_STUDIO_BRIDGE_URL = url;
  process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN = "first-generation-token";
  let registered;
  register({ registerTool(definition) { registered = definition; }, on() {} });
  return registered;
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
