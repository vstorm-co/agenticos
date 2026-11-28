import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("./api-client", () => ({ apiClient: { post } }));

import { mcpAppCallTool, mcpAppFrameUrl, mcpAppReadResource } from "./mcp-apps-api";

// A provider's call id can hold characters a path cannot.
const ROOT = "/conversations/c-1/tool-calls/call%2F1%3Fx/app";

describe("mcp-apps-api", () => {
  beforeEach(() => post.mockReset());

  it("asks for the page's signed address and answers with it alone", async () => {
    post.mockResolvedValue({ url: "https://content.example/mcp-app/token" });

    await expect(mcpAppFrameUrl("c-1", "call/1?x")).resolves.toBe(
      "https://content.example/mcp-app/token",
    );
    expect(post).toHaveBeenCalledWith(ROOT);
  });

  it("relays a page's tool call with its name and arguments", async () => {
    const result = { content: [], isError: false };
    post.mockResolvedValue(result);

    await expect(mcpAppCallTool("c-1", "call/1?x", "get_series", { range: "7d" })).resolves.toBe(
      result,
    );
    expect(post).toHaveBeenCalledWith(`${ROOT}/tools-call`, {
      name: "get_series",
      arguments: { range: "7d" },
    });
  });

  it("relays a page's resource read by its address", async () => {
    const read = { contents: [] };
    post.mockResolvedValue(read);

    await expect(mcpAppReadResource("c-1", "call/1?x", "ui://widget")).resolves.toBe(read);
    expect(post).toHaveBeenCalledWith(`${ROOT}/resources-read`, { uri: "ui://widget" });
  });
});
