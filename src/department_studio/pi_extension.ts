import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type RoomArguments = { text: string; recipients?: string[] };

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

  pi.registerTool({
    name: "send_room_message",
    label: "Post to shared room",
    description: "Store a public room message. Optional explicit recipient handles request peer "
      + "replies within the originating human request. No recipients means public information only. "
      + "An acknowledgement confirms storage, not completion. Never include private reasoning or secrets.",
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
      const timeout = AbortSignal.timeout(15000);
      const response = await fetch(url, {
        method: "POST",
        redirect: "error",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ call_id: toolCallId, text: params.text, recipients: params.recipients ?? [] }),
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      });
      if (!response.ok) {
        // Server internals and proxy error pages never become a native tool result.
        await response.body?.cancel();
        throw new Error(`Room post failed (HTTP ${response.status}). No acknowledgement was received.`);
      }
      const receipt = await response.json();
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
