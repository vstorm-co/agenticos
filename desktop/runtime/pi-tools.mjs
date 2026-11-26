import { createHash } from "node:crypto";
import { localRequest } from "./platform-http.mjs";

/** @typedef {Record<string, unknown>} JsonObject */
/** @typedef {{ registerTool: (definition: { name: string, label: string, description: string, parameters: JsonObject, execute: (id: string, args: JsonObject, signal?: AbortSignal) => Promise<{content: {type: 'text', text: string}[], details: JsonObject}> }) => void }} Pi */
/** @param {unknown} value @returns {value is JsonObject} */
function object(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param {Pi} pi */
export default async function platformTools(pi) {
  const url = process.env.AGENTICOS_BRIDGE_URL;
  const token = process.env.AGENTICOS_BRIDGE_TOKEN;
  delete process.env.AGENTICOS_BRIDGE_URL;
  delete process.env.AGENTICOS_BRIDGE_TOKEN;
  if (
    !url ||
    !/^http:\/\/127\.0\.0\.1:[0-9]+\/mcp$/.test(url) ||
    !token ||
    !/^[a-f0-9]{64}$/.test(token)
  )
    throw new Error("No owned platform bridge");

  const endpoint = url;

  /** @param {string} method @param {JsonObject} params @param {AbortSignal | undefined} signal */
  async function rpc(method, params, signal) {
    const id = crypto.randomUUID();
    const active = signal
      ? AbortSignal.any([signal, AbortSignal.timeout(300000)])
      : AbortSignal.timeout(300000);
    /** @type {Promise<unknown> | undefined} */
    let cancellation;
    const cancel = () => {
      cancellation = localRequest(endpoint, {
        signal: AbortSignal.timeout(5000),
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "notifications/cancelled",
          params: { requestId: id },
        }),
      }).catch(() => undefined);
    };
    active.addEventListener("abort", cancel, { once: true });
    try {
      const response = await localRequest(endpoint, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
        signal: active,
      });
      if (response.status === 202) return {};
      if (!response.ok || !response.body)
        throw new Error("The platform bridge refused this operation");
      const reader = response.body.getReader();
      let size = 0;
      const chunks = [];
      try {
        for (;;) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > 2 << 20)
            throw new Error(
              "The platform result exceeds the Pi bridge limit; do not repeat the action",
            );
          chunks.push(part.value);
        }
      } finally {
        await reader.cancel();
      }
      const frame = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (
        !object(frame) ||
        frame.id !== id ||
        !object(frame.result) ||
        frame.error !== undefined
      )
        throw new Error(
          "The platform action has no successful result; do not retry automatically",
        );
      return frame.result;
    } finally {
      active.removeEventListener("abort", cancel);
      await cancellation;
    }
  }
  await rpc(
    "initialize",
    {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "AgenticOS Pi bridge", version: "1.0.0" },
    },
    undefined,
  );
  const catalog = await rpc("tools/list", {}, undefined);
  if (!Array.isArray(catalog.tools) || catalog.tools.length > 512)
    throw new Error("Unsupported platform tool catalog");
  for (const tool of catalog.tools) {
    if (
      !object(tool) ||
      typeof tool.name !== "string" ||
      typeof tool.description !== "string" ||
      !object(tool.inputSchema)
    )
      throw new Error("Malformed platform tool definition");
    const name = tool.name;
    pi.registerTool({
      name: `agenticos_${createHash("sha256").update(name).digest("hex").slice(0, 24)}`,
      label: `AgenticOS: ${name}`,
      description: tool.description,
      parameters: tool.inputSchema,
      async execute(_id, args, signal) {
        const result = await rpc(
          "tools/call",
          { name, arguments: args },
          signal,
        );
        if (result.isError === true)
          throw new Error(
            "The platform refused this action or could not confirm its result. Do not claim success or retry automatically.",
          );
        if (
          !Array.isArray(result.content) ||
          result.content.some(
            (item) =>
              !object(item) ||
              item.type !== "text" ||
              typeof item.text !== "string",
          )
        )
          throw new Error("Unsupported platform result");
        return {
          content: result.content.map((item) => ({
            type: "text",
            text: String(item.text),
          })),
          details: {},
        };
      },
    });
  }
}
