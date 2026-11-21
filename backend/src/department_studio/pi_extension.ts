import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type RoomArguments = { text: string; recipients?: string[] };
type RecordArguments = { name: string; content?: string; mode?: "append" | "replace" };
const RECORD_NAME = "^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\\.md$";

export default function registerRoomBridge(pi: ExtensionAPI) {
  // Capture once. A child belongs to one immutable delivery and generation.
  const token = process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN;
  const address = process.env.DEPARTMENT_STUDIO_BRIDGE_URL;
  if (!token || !address) throw new Error("Room bridge credentials are missing.");
  const url = new URL(address);
  const local = url.hostname === "[::1]" || /^127\.(\d{1,3}\.){2}\d{1,3}$/.test(url.hostname);
  if (!local || url.protocol !== "http:" || url.pathname !== "/api/bridge/messages"
      || url.username || url.password || url.search || url.hash) {
    throw new Error("Room bridge must use the configured loopback endpoint.");
  }
  const bridgeRoot = `${url.origin}/api/bridge`;

  async function bridgeFetch(path: string, init: RequestInit = {}, signal?: AbortSignal) {
    const timeout = AbortSignal.timeout(15000);
    const response = await fetch(`${bridgeRoot}${path}`, {
      ...init,
      redirect: "error",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(init.headers || {}),
      },
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
    if (!response.ok) {
      await response.body?.cancel();
      throw new Error(`Room bridge failed (HTTP ${response.status}). No acknowledgement was received.`);
    }
    const payload = await response.json();
    if (!payload || typeof payload !== "object") {
      throw new Error("Room bridge returned an invalid acknowledgement.");
    }
    return payload;
  }

  pi.registerTool({
    name: "list_records",
    label: "List project records",
    description: "List durable Markdown records for this project. Use these for audit notes; keep room messages short.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute(_toolCallId: string, _params: RecordArguments, signal?: AbortSignal) {
      const payload = await bridgeFetch("/records", {}, signal);
      const records = Array.isArray(payload.records) ? payload.records : [];
      const lines = records.map((record: { name: string; size: number }) => `${record.name} (${record.size} bytes)`);
      return {
        content: [{ type: "text", text: lines.length ? lines.join("\n") : "No records yet." }],
        details: { records },
      };
    },
  });

  pi.registerTool({
    name: "read_record",
    label: "Read project record",
    description: "Read one Markdown record from the project records folder by exact filename.",
    parameters: {
      type: "object",
      properties: { name: { type: "string", pattern: RECORD_NAME } },
      required: ["name"],
      additionalProperties: false,
    },
    async execute(_toolCallId: string, params: RecordArguments, signal?: AbortSignal) {
      const payload = await bridgeFetch(`/records/${encodeURIComponent(params.name)}`, {}, signal);
      if (typeof payload.content !== "string" || typeof payload.path !== "string") {
        throw new Error("Room bridge returned an invalid record.");
      }
      return {
        content: [{ type: "text", text: payload.content }],
        details: { name: payload.name, path: payload.path },
      };
    },
  });

  pi.registerTool({
    name: "write_record",
    label: "Write project record",
    description: "Append to or replace one Markdown record in the project records folder. Reference the exact path in the room instead of pasting the content.",
    parameters: {
      type: "object",
      properties: {
        name: { type: "string", pattern: RECORD_NAME },
        content: { type: "string", minLength: 1, maxLength: 524288 },
        mode: { type: "string", enum: ["append", "replace"], default: "append" },
      },
      required: ["name", "content"],
      additionalProperties: false,
    },
    async execute(_toolCallId: string, params: RecordArguments, signal?: AbortSignal) {
      const payload = await bridgeFetch("/records", {
        method: "POST",
        body: JSON.stringify({ name: params.name, content: params.content, mode: params.mode || "append" }),
      }, signal);
      return {
        content: [{ type: "text", text: `Record saved: ${payload.path} (${payload.size} bytes).` }],
        details: { name: payload.name, path: payload.path, size: payload.size },
      };
    },
  });

  pi.registerTool({
    name: "send_room_message",
    label: "Post to shared room",
    description: "Store a brief public room message. Optional explicit recipient handles request peer replies within the originating human request. No recipients means public information only. Put durable details in project records and reference the file path. An acknowledgement confirms storage, not completion. Never include private reasoning or secrets.",
    parameters: {
      type: "object",
      properties: {
        text: { type: "string", minLength: 1, maxLength: 32000 },
        recipients: {
          type: "array", maxItems: 8,
          items: { type: "string", pattern: "^[a-zA-Z][a-zA-Z0-9_-]{0,31}$" },
          description: "Recipient handles without @. Do not address yourself or use all.",
        },
      },
      required: ["text"],
      additionalProperties: false,
    },
    async execute(toolCallId: string, params: RoomArguments, signal?: AbortSignal) {
      const receipt = await bridgeFetch("/messages", {
        method: "POST",
        body: JSON.stringify({ call_id: toolCallId, text: params.text, recipients: params.recipients ?? [] }),
      }, signal);
      if (typeof receipt.message_id !== "string" || !Array.isArray(receipt.recipient_ids)
          || !receipt.recipient_ids.every((id: unknown) => typeof id === "string")
          || (receipt.notice !== null && typeof receipt.notice !== "string")) {
        throw new Error("Room returned an invalid acknowledgement.");
      }
      const details = {
        message_id: receipt.message_id,
        recipient_ids: receipt.recipient_ids,
        notice: receipt.notice,
      };
      return {
        content: [{ type: "text", text: "Message stored. "
          + (details.notice || `${details.recipient_ids.length} recipient deliveries queued.`) }],
        details,
      };
    },
  });

  // The host verifies registration before it is allowed to send a model prompt.
  pi.on("session_start", (_event, ctx) => {
    ctx.ui.notify("department-studio-bridge-ready-v1", "info");
  });
}
