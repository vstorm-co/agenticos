// @vitest-environment node
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

let child: ChildProcessWithoutNullStreams;
let endpoint: string;

beforeAll(async () => {
  child = spawn(
    "bun",
    ["run", fileURLToPath(new URL("./e2e/stub-model-server.ts", import.meta.url))],
    {
      env: { ...process.env, E2E_STUB_MODEL_PORT: "0", E2E_STUB_MODEL_BIND: "127.0.0.1" },
    },
  );
  endpoint = await new Promise<string>((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Stub did not start")), 5_000);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Stub exited before listening: ${code}`));
    });
    child.stdout.on("data", (data: Buffer) => {
      output = (output + data.toString()).slice(-2_048);
      const address = /listening on (http:\/\/127\.0\.0\.1:\d+)/.exec(output)?.[1];
      if (address) {
        clearTimeout(timeout);
        resolve(address);
      }
    });
  });
});

afterAll(async () => {
  if (child && child.exitCode === null && child.signalCode === null) {
    const stopped = once(child, "exit");
    child.kill("SIGTERM");
    await stopped;
  }
});

const output = {
  type: "function",
  function: {
    name: "final_result",
    parameters: { type: "object", properties: { problems: { type: "array" } } },
  },
};

async function complete(body: object): Promise<Response> {
  const response = await fetch(`${endpoint}/v1/chat/completions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  expect(response.status).toBe(200);
  return response;
}

describe("the E2E provider's structured-output contract", () => {
  it("returns the declared output tool instead of prose JSON for a system agent", async () => {
    const response = await complete({
      messages: [{ role: "user", content: "E2E-SKILL" }],
      tools: [output],
    });
    expect(await response.json()).toMatchObject({
      choices: [
        {
          finish_reason: "tool_calls",
          message: {
            content: null,
            tool_calls: [
              {
                function: {
                  name: "final_result",
                  arguments: expect.stringContaining('"cause":"skill"'),
                },
              },
            ],
          },
        },
      ],
    });
  });

  it("streams the same output-tool protocol", async () => {
    const response = await complete({
      messages: [{ role: "user", content: "E2E-SKILL" }],
      tools: [output],
      stream: true,
    });
    const frames = await response.text();
    expect(frames).toContain('"name":"final_result"');
    expect(frames).toContain('"finish_reason":"tool_calls"');
    expect(frames).toContain("data: [DONE]");
  });

  it("does not invent a structured answer without the journey's explicit fixture marker", async () => {
    const response = await complete({
      messages: [{ role: "user", content: "Reply with PONG-CONTROL" }],
      tools: [output],
    });
    expect(await response.json()).toMatchObject({
      choices: [{ finish_reason: "stop", message: { content: "PONG-CONTROL" } }],
    });
  });

  it("performs an explicitly requested business tool before the final answer", async () => {
    const args = Buffer.from(JSON.stringify({ id: "policy" })).toString("base64url");
    const response = await complete({
      messages: [{ role: "user", content: `E2E-SKILL CALL-TOOL:read_skill:${args}` }],
      tools: [output, { type: "function", function: { name: "read_skill" } }],
    });
    expect(await response.json()).toMatchObject({
      choices: [{ message: { tool_calls: [{ function: { name: "read_skill" } }] } }],
    });
  });
});
