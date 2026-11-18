import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { PlatformBridge } from "./platform-bridge.mts";

const owned: PlatformBridge[] = [];
afterEach(async () => {
  await Promise.all(owned.splice(0).map((bridge) => bridge.close()));
});
async function start(
  answer = true,
): Promise<{ bridge: PlatformBridge; frames: Record<string, unknown>[] }> {
  const frames: Record<string, unknown>[] = [];
  const bridge = new PlatformBridge(async (frame) => {
    frames.push(frame);
    if (answer)
      queueMicrotask(() =>
        bridge.accept({
          id: frame.id,
          result:
            frame.method === "_agenticos/tools/list"
              ? { tools: [] }
              : { content: [{ type: "text", text: "done" }], isError: false },
        }),
      );
  });
  owned.push(bridge);
  await bridge.listen();
  return { bridge, frames };
}
function headers(bridge: PlatformBridge): Record<string, string> {
  return {
    Authorization: `Bearer ${bridge.environment().AGENTICOS_BRIDGE_TOKEN}`,
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
}
function post(
  bridge: PlatformBridge,
  id: number,
  method: string,
  params: Record<string, unknown> = {},
): Promise<Response> {
  return fetch(bridge.url, {
    method: "POST",
    headers: headers(bridge),
    body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
  });
}

test("local MCP requires its exact authority, rejects browser origins and provides no GET stream", async () => {
  const { bridge, frames } = await start();
  assert.equal((await fetch(bridge.url)).status, 403);
  assert.equal(
    (await fetch(bridge.url, { headers: headers(bridge) })).status,
    405,
  );
  assert.equal(
    (
      await fetch(bridge.url, {
        method: "POST",
        headers: { ...headers(bridge), Origin: "https://example.com" },
        body: "{}",
      })
    ).status,
    403,
  );
  const initialized = await (
    await post(bridge, 1, "initialize", { protocolVersion: "2025-06-18" })
  ).json();
  assert.equal(initialized.result.protocolVersion, "2025-06-18");
  assert.deepEqual(initialized.result.capabilities, { tools: {} });
  assert.equal(frames.length, 0);
  const listed = await (await post(bridge, 2, "tools/list")).json();
  assert.deepEqual(listed.result, { tools: [] });
  assert.equal(frames[0]?.method, "_agenticos/tools/list");
});

test("concurrent duplicate action requests execute once and conflicting replays are refused", async () => {
  const { bridge, frames } = await start();
  const responses = await Promise.all([
    post(bridge, 8, "tools/call", {
      name: "write",
      arguments: { text: "original" },
    }),
    post(bridge, 8, "tools/call", {
      name: "write",
      arguments: { text: "original" },
    }),
  ]);
  assert.deepEqual(await responses[0]!.json(), await responses[1]!.json());
  assert.equal(frames.length, 1);
  assert.equal(
    (
      await post(bridge, 8, "tools/call", {
        name: "write",
        arguments: { text: "changed" },
      })
    ).status,
    400,
  );
  assert.equal(frames.length, 1);
  assert.equal(
    bridge.accept({ id: frames[0]?.id, result: { late: true } }),
    true,
  );
  assert.equal(bridge.accept({ id: "vendor-request", result: {} }), false);
});

test("request size and protocol are checked before forwarding any platform operation", async () => {
  const { bridge, frames } = await start();
  assert.equal(
    (
      await post(bridge, 4, "tools/call", {
        name: "write",
        arguments: { text: "x".repeat(128 << 10) },
      })
    ).status,
    413,
  );
  assert.equal(
    (
      await fetch(bridge.url, {
        method: "POST",
        headers: { ...headers(bridge), "MCP-Protocol-Version": "unsupported" },
        body: "{}",
      })
    ).status,
    400,
  );
  assert.equal(frames.length, 0);
});

test("vendor error content and credential diagnostics are never exposed as tool results", async () => {
  let bridge: PlatformBridge;
  bridge = new PlatformBridge(async (frame) => {
    queueMicrotask(() =>
      bridge.accept({
        id: frame.id,
        error: { message: "sensitive-vendor-diagnostic" },
      }),
    );
  });
  owned.push(bridge);
  await bridge.listen();
  const result = await (
    await post(bridge, 1, "tools/call", { name: "write" })
  ).text();
  assert.match(result, /Do not retry/);
  assert.equal(result.includes("sensitive-vendor-diagnostic"), false);
});

test("explicit MCP cancellation cancels the owned backend request without claiming success", async () => {
  const { bridge, frames } = await start(false);
  const request = post(bridge, 42, "tools/call", { name: "write" });
  while (frames.length === 0)
    await new Promise<void>((resolve) => setImmediate(resolve));
  const cancelled = await fetch(bridge.url, {
    method: "POST",
    headers: headers(bridge),
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "notifications/cancelled",
      params: { requestId: 42 },
    }),
  });
  assert.equal(cancelled.status, 202);
  const result = await (await request).json();
  assert.equal(result.error.code, -32000);
  assert.equal(frames[1]?.method, "_agenticos/cancel_request");
  assert.deepEqual(frames[1]?.params, { id: frames[0]?.id });
});

test("MCP progress streams finish with the correlated result", async () => {
  const { bridge, frames } = await start();
  const result = await post(bridge, 9, "tools/call", {
    name: "write",
    arguments: {},
    _meta: { progressToken: "waiting" },
  });
  assert.match(result.headers.get("content-type") ?? "", /text\/event-stream/);
  const text = await result.text();
  assert.match(text, /event: message/);
  assert.match(text, /"id":9/);
  assert.deepEqual(frames[0]?.params, { name: "write", arguments: {} });
});

test("Pi registers the prepared platform schemas and never persists bootstrap authority", async () => {
  const { default: platformTools } = await import("./pi-tools.mjs");
  const registrations: Parameters<
    Parameters<typeof platformTools>[0]["registerTool"]
  >[0][] = [];
  let bridge: PlatformBridge;
  bridge = new PlatformBridge(async (frame) => {
    queueMicrotask(() =>
      bridge.accept({
        id: frame.id,
        result:
          frame.method === "_agenticos/tools/list"
            ? {
                tools: [
                  {
                    name: "calculate",
                    description: "Add a number",
                    inputSchema: {
                      type: "object",
                      properties: { value: { type: "integer" } },
                      required: ["value"],
                    },
                  },
                ],
              }
            : { content: [{ type: "text", text: "3" }], isError: false },
      }),
    );
  });
  owned.push(bridge);
  await bridge.listen();
  Object.assign(process.env, bridge.environment());
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("A vendor global dispatcher must not receive local bridge authority"); };
  try {
    await platformTools({ registerTool: (tool) => registrations.push(tool) });
    assert.equal(process.env.AGENTICOS_BRIDGE_TOKEN, undefined);
    assert.equal(process.env.AGENTICOS_BRIDGE_URL, undefined);
    assert.equal(registrations.length, 1);
    const tool = registrations[0]!;
    assert.match(tool.name, /^agenticos_[a-f0-9]{24}$/);
    assert.equal(tool.parameters.type, "object");
    assert.deepEqual((await tool.execute("native", { value: 2 })).content, [
      { type: "text", text: "3" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.AGENTICOS_BRIDGE_TOKEN;
    delete process.env.AGENTICOS_BRIDGE_URL;
  }
});
