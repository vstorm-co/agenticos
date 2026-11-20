import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import type { Readable, Writable } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";

import { localRequest } from "./platform-http.mjs";

type ObjectValue = Record<string, unknown>;
type Emit = (frame: ObjectValue) => Promise<void>;
const MAX_FRAME = 2 << 20;
const PROTOCOLS = new Set(["2025-03-26", "2025-06-18", "2025-11-25"]);
export function object(value: unknown): value is ObjectValue {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One owned process's loopback MCP endpoint; no AgenticOS access token exists here. */
export class PlatformBridge {
  private readonly token = randomBytes(32).toString("hex");
  private readonly pending = new Map<
    string,
    { resolve: (value: unknown) => void; reject: () => void }
  >();
  private readonly history = new Map<
    string,
    { hash: string; result: Promise<ObjectValue> }
  >();
  private readonly active = new Map<string, string>();
  private retained = 0;
  private closed = false;
  private readonly catalogReady = new AbortController();
  private readonly emit: Emit;
  private readonly server = createServer((request, response) => {
    void this.serve(request, response).catch(() => {
      if (!response.headersSent) response.writeHead(400);
      response.end();
    });
  });
  url = "";

  constructor(emit: Emit) {
    this.emit = emit;
    this.server.requestTimeout = 10000;
    this.server.headersTimeout = 5000;
    this.server.maxHeadersCount = 32;
    this.server.maxConnections = 16;
  }

  async listen(): Promise<void> {
    this.server.listen(0, "127.0.0.1");
    await once(this.server, "listening");
    const address = this.server.address();
    if (!address || typeof address === "string")
      throw new Error("No bridge endpoint");
    this.url = `http://127.0.0.1:${address.port}/mcp`;
  }

  async waitReady(): Promise<void> {
    if (this.catalogReady.signal.aborted) return;
    await new Promise<void>((resolve, reject) => {
      const ready = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(() => {
        this.catalogReady.signal.removeEventListener("abort", ready);
        reject(
          new Error(
            "The runtime did not discover its scoped platform tools; no prompt was sent",
          ),
        );
      }, 10000);
      this.catalogReady.signal.addEventListener("abort", ready, { once: true });
    });
  }

  environment(): Record<string, string> {
    return {
      AGENTICOS_BRIDGE_URL: this.url,
      AGENTICOS_BRIDGE_TOKEN: this.token,
    };
  }

  serverDefinition(): ObjectValue {
    return {
      name: "agenticos_platform",
      command: process.execPath,
      args: [fileURLToPath(import.meta.url), "client"],
      env: Object.entries(this.environment()).map(([name, value]) => ({
        name,
        value,
      })),
    };
  }

  accept(frame: ObjectValue): boolean {
    const id = frame.id;
    if (typeof id !== "string" || !id.startsWith("agenticos-bridge-"))
      return false;
    const pending = this.pending.get(id);
    if (pending) {
      this.pending.delete(id);
      if (frame.error !== undefined) pending.reject();
      else pending.resolve(frame.result);
    }
    // Late responses must never be mistaken for vendor commands.
    return true;
  }

  private async dispatch(
    method: string,
    params: ObjectValue,
    nativeId: unknown,
  ): Promise<ObjectValue> {
    if (this.closed || this.pending.size >= 8)
      throw new Error("Bridge unavailable");
    const id = `agenticos-bridge-${randomBytes(16).toString("hex")}`;
    let rejectRequest: () => void = () => {};
    const result = new Promise<unknown>((resolve, reject) => {
      rejectRequest = () =>
        reject(
          new Error(
            "Native tool operation ended without a known result; do not retry automatically",
          ),
        );
      this.pending.set(id, { resolve, reject: rejectRequest });
    });
    this.active.set(JSON.stringify(nativeId), id);
    void result.catch(() => {});
    const timer = setTimeout(() => {
      rejectRequest();
      void this.emit({
        jsonrpc: "2.0",
        method: "_agenticos/cancel_request",
        params: { id },
      }).catch(() => {});
    }, 300000);
    try {
      await this.emit({
        jsonrpc: "2.0",
        id,
        method: `_agenticos/${method}`,
        params,
      });
      const value = await result;
      if (
        !object(value) ||
        Buffer.byteLength(JSON.stringify(value)) > MAX_FRAME
      )
        throw new Error("Unsupported bridge response");
      return value;
    } finally {
      clearTimeout(timer);
      this.pending.delete(id);
      this.active.delete(JSON.stringify(nativeId));
    }
  }

  private async handle(frame: ObjectValue): Promise<ObjectValue> {
    if (frame.method === "initialize") {
      const requested = object(frame.params)
        ? frame.params.protocolVersion
        : undefined;
      return {
        protocolVersion:
          typeof requested === "string" && PROTOCOLS.has(requested)
            ? requested
            : "2025-06-18",
        capabilities: { tools: {} },
        serverInfo: { name: "AgenticOS run tools", version: "1.0.0" },
      };
    }
    if (frame.method === "ping") return {};
    if (frame.method !== "tools/list" && frame.method !== "tools/call")
      throw new Error("Unsupported MCP operation");
    const raw = object(frame.params) ? frame.params : {};
    if (frame.method === "tools/list" && raw.cursor !== undefined)
      throw new Error("Unsupported catalog cursor");
    const params =
      frame.method === "tools/call"
        ? { name: raw.name, arguments: raw.arguments ?? {} }
        : {};
    const result = await this.dispatch(frame.method, params, frame.id);
    if (frame.method === "tools/list") this.catalogReady.abort();
    return result;
  }

  private async serve(
    request: IncomingMessage,
    response: ServerResponse,
  ): Promise<void> {
    const supplied = request.headers.authorization;
    const expected = `Bearer ${this.token}`;
    if (
      this.closed ||
      request.url !== "/mcp" ||
      request.headers.origin !== undefined ||
      request.headers.host !== new URL(this.url).host ||
      typeof supplied !== "string" ||
      Buffer.byteLength(supplied) !== Buffer.byteLength(expected) ||
      !timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
    ) {
      response.writeHead(403).end();
      return;
    }
    if (request.method !== "POST") {
      response.writeHead(405, { Allow: "POST" }).end();
      return;
    }
    const protocol = request.headers["mcp-protocol-version"];
    if (
      protocol !== undefined &&
      (typeof protocol !== "string" || !PROTOCOLS.has(protocol))
    ) {
      response.writeHead(400).end();
      return;
    }
    if (!request.headers["content-type"]?.startsWith("application/json")) {
      response.writeHead(415).end();
      return;
    }
    let body = "";
    request.setEncoding("utf8");
    for await (const chunk of request) {
      body += String(chunk);
      if (Buffer.byteLength(body) > 128 << 10) {
        response.writeHead(413).end();
        return;
      }
    }
    const frame: unknown = JSON.parse(body);
    if (
      !object(frame) ||
      frame.jsonrpc !== "2.0" ||
      typeof frame.method !== "string"
    )
      throw new Error("Invalid MCP request");
    if (frame.id === undefined) {
      if (frame.method === "notifications/cancelled" && object(frame.params)) {
        const id = this.active.get(JSON.stringify(frame.params.requestId));
        if (id) {
          await this.emit({
            jsonrpc: "2.0",
            method: "_agenticos/cancel_request",
            params: { id },
          });
          this.pending.get(id)?.reject();
        }
      }
      response.writeHead(202).end();
      return;
    }
    if (typeof frame.id !== "string" && typeof frame.id !== "number")
      throw new Error("Invalid MCP id");
    const key = JSON.stringify(frame.id);
    const hash = createHash("sha256").update(body).digest("hex");
    let entry = this.history.get(key);
    if (entry?.hash !== undefined && entry.hash !== hash)
      throw new Error("Reused request id");
    if (!entry) {
      if (this.history.size >= 4096 || this.retained >= 8 << 20)
        throw new Error("Bridge retention limit");
      // Store the promise before admitting the call: a concurrent replay cannot execute twice.
      const result = this.handle(frame)
        .then(
          (value) => ({ jsonrpc: "2.0", id: frame.id, result: value }),
          () => ({
            jsonrpc: "2.0",
            id: frame.id,
            error: {
              code: -32000,
              message:
                "The platform tool did not return a known successful result. Do not retry an action automatically.",
            },
          }),
        )
        .then((value) => {
          const bytes = Buffer.byteLength(JSON.stringify(value));
          this.retained += bytes;
          if (this.retained > 8 << 20)
            return {
              jsonrpc: "2.0",
              id: frame.id,
              error: {
                code: -32000,
                message:
                  "Result retention limit; the action must not be repeated automatically",
              },
            };
          return value;
        });
      entry = { hash, result };
      this.history.set(key, entry);
    }
    const meta =
      object(frame.params) && object(frame.params._meta)
        ? frame.params._meta
        : {};
    const progressToken = meta.progressToken;
    if (
      typeof progressToken === "string" ||
      typeof progressToken === "number"
    ) {
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store",
      });
      response.flushHeaders();
      let progress = 0;
      const timer = setInterval(() => {
        response.write(
          `event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", method: "notifications/progress", params: { progressToken, progress: ++progress } })}\n\n`,
        );
      }, 20000);
      try {
        response.end(
          `event: message\ndata: ${JSON.stringify(await entry.result)}\n\n`,
        );
      } finally {
        clearInterval(timer);
      }
    } else {
      response.writeHead(200, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      });
      response.end(JSON.stringify(await entry.result));
    }
  }

  async close(): Promise<void> {
    this.closed = true;
    for (const request of this.pending.values()) request.reject();
    this.pending.clear();
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }
}

export async function write(
  stream: Writable,
  frame: ObjectValue,
): Promise<void> {
  if (!stream.write(`${JSON.stringify(frame)}\n`)) await once(stream, "drain");
}

/** Bound before parsing, including a child that never terminates its line. */
export async function lines(
  stream: Readable,
  accept: (frame: ObjectValue) => Promise<void>,
): Promise<void> {
  let buffer = "";
  stream.setEncoding("utf8");
  for await (const chunk of stream) {
    buffer += String(chunk);
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      if (Buffer.byteLength(buffer.slice(0, newline)) > MAX_FRAME)
        throw new Error("Native frame limit");
      const text = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!text.trim()) continue;
      const frame: unknown = JSON.parse(text);
      if (!object(frame)) throw new Error("Invalid native frame");
      await accept(frame);
    }
    if (Buffer.byteLength(buffer) > MAX_FRAME)
      throw new Error("Native frame limit");
  }
  if (buffer.trim()) throw new Error("Truncated native frame");
}

async function client(): Promise<void> {
  const url = process.env.AGENTICOS_BRIDGE_URL;
  const token = process.env.AGENTICOS_BRIDGE_TOKEN;
  if (
    !url ||
    !/^http:\/\/127\.0\.0\.1:[0-9]+\/mcp$/.test(url) ||
    !token ||
    !/^[a-f0-9]{64}$/.test(token)
  )
    throw new Error("No owned bridge");
  const endpoint = url;
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  const pending = new Set<Promise<void>>();
  const controller = new AbortController();
  let failed = false;
  async function forward(frame: ObjectValue): Promise<void> {
    const response = await localRequest(endpoint, {
      headers,
      body: JSON.stringify(frame),
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(310000)]),
    });
    if (response.status === 202) return;
    if (!response.ok || !response.body)
      throw new Error("Native bridge refused the request");
    const sse = response.headers
      .get("content-type")
      ?.startsWith("text/event-stream");
    const reader = response.body
      .pipeThrough(new TextDecoderStream())
      .getReader();
    let buffer = "";
    let total = 0;
    try {
      for (;;) {
        const part = await reader.read();
        if (part.done) break;
        total += Buffer.byteLength(part.value);
        buffer += part.value;
        if (total > 8 << 20 || Buffer.byteLength(buffer) > MAX_FRAME)
          throw new Error("Native response limit");
        if (sse) {
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const data = event
              .split("\n")
              .filter((line) => line.startsWith("data: "))
              .map((line) => line.slice(6))
              .join("\n");
            if (data) {
              const parsed: unknown = JSON.parse(data);
              if (!object(parsed)) throw new Error("Invalid MCP response");
              await write(process.stdout, parsed);
            }
          }
        }
      }
      if (!sse) {
        const parsed: unknown = JSON.parse(buffer);
        if (!object(parsed)) throw new Error("Invalid MCP response");
        await write(process.stdout, parsed);
      } else if (buffer.trim()) throw new Error("Truncated MCP response");
    } finally {
      await reader.cancel();
    }
  }
  try {
    await lines(process.stdin, async (frame) => {
      if (failed || pending.size >= 8)
        throw new Error("Native bridge concurrency limit");
      let task: Promise<void>;
      task = forward(frame)
        .catch(() => {
          failed = true;
          process.stdin.destroy();
        })
        .finally(() => pending.delete(task));
      pending.add(task);
    });
    await Promise.all(pending);
  } finally {
    controller.abort();
    await Promise.allSettled(pending);
  }
  if (failed)
    throw new Error("Native bridge stopped without a successful result");
}

async function main(): Promise<void> {
  const mode = process.argv[2];
  if (mode === "client") return client();
  const program = process.argv[3];
  if ((mode !== "acp" && mode !== "pi") || !program)
    throw new Error("Invalid native launch");
  const bridge = new PlatformBridge((frame) => write(process.stdout, frame));
  await bridge.listen();
  const args = process.argv.slice(4);
  if (mode === "pi")
    args.push(
      "--extension",
      fileURLToPath(new URL("pi-tools.mjs", import.meta.url)),
    );
  const child = spawn(program, args, {
    cwd: process.cwd(),
    env: { ...process.env, ...bridge.environment() },
    stdio: ["pipe", "pipe", "pipe"],
    shell: false,
  });
  // Paths and native credential diagnostics never enter the RPC or saved trace.
  child.stderr.resume();
  const completion = once(child, "exit");
  const input = lines(process.stdin, async (frame) => {
    if (bridge.accept(frame)) return;
    if (
      mode === "acp" &&
      (frame.method === "session/new" || frame.method === "session/load")
    ) {
      if (
        !object(frame.params) ||
        !Array.isArray(frame.params.mcpServers) ||
        frame.params.mcpServers.length
      )
        throw new Error("Unadmitted native MCP config");
      frame.params.mcpServers = [bridge.serverDefinition()];
    }
    if (mode === "acp" && frame.method === "session/prompt")
      await bridge.waitReady();
    await write(child.stdin, frame);
  });
  const output = lines(child.stdout, (frame) => {
    if (
      (typeof frame.method === "string" &&
        frame.method.startsWith("_agenticos/tools/")) ||
      (typeof frame.id === "string" && frame.id.startsWith("agenticos-bridge-"))
    )
      throw new Error(
        "The vendor attempted to use the reserved bridge namespace",
      );
    return write(process.stdout, frame);
  });
  try {
    await Promise.race([input, output, completion]);
  } finally {
    child.kill();
    const kill = setTimeout(() => child.kill("SIGKILL"), 2000);
    process.stdin.destroy();
    child.stdin.destroy();
    child.stdout.destroy();
    await bridge.close();
    await Promise.allSettled([input, output, completion]);
    clearTimeout(kill);
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch(() => {
    process.stderr.write(
      "The owned native platform bridge stopped without a known result.\n",
    );
    process.exitCode = 1;
  });
}
