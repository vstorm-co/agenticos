import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./api-error";
import {
  INVALID_PARAMS,
  MCP_APPS_PROTOCOL,
  METHOD_NOT_FOUND,
  SERVER_ERROR,
  answer,
  asMessage,
  openableUrl,
  type HostActions,
} from "./mcp-app-host";

const context = { theme: "dark" as const, locale: "de", toolName: "charts_data_query" };

function actions(overrides: Partial<HostActions> = {}): HostActions {
  return {
    callTool: vi.fn().mockResolvedValue({ content: [], isError: false }),
    readResource: vi.fn().mockResolvedValue({ contents: [] }),
    openLink: vi.fn(),
    ...overrides,
  };
}

function request(method: string, params: Record<string, unknown> = {}) {
  return { jsonrpc: "2.0" as const, id: 7, method, params };
}

describe("asMessage", () => {
  it("reads JSON-RPC 2.0 and nothing else", () => {
    expect(asMessage({ jsonrpc: "2.0", id: 1, method: "ping" })).toMatchObject({
      id: 1,
      method: "ping",
    });
    expect(asMessage({ type: "agenticos:visual-ready" })).toBeNull();
    expect(asMessage("ping")).toBeNull();
    expect(asMessage(null)).toBeNull();
  });

  it("drops an id or params of the wrong shape rather than passing them on", () => {
    expect(asMessage({ jsonrpc: "2.0", id: {}, method: "ping", params: "x" })).toEqual({
      jsonrpc: "2.0",
      id: undefined,
      method: "ping",
      params: {},
    });
  });
});

describe("answer", () => {
  it("introduces the host on ui/initialize, with the theme, locale and tool", async () => {
    const reply = await answer(request("ui/initialize"), context, actions());

    expect(reply).toMatchObject({
      id: 7,
      result: {
        protocolVersion: MCP_APPS_PROTOCOL,
        hostCapabilities: { serverTools: {}, serverResources: {}, openLinks: {} },
        hostContext: {
          theme: "dark",
          locale: "de",
          displayMode: "inline",
          toolInfo: { tool: { name: "charts_data_query" } },
        },
      },
    });
  });

  it("answers ping, and keeps the page inline whatever mode it asks for", async () => {
    expect(await answer(request("ping"), context, actions())).toEqual({
      jsonrpc: "2.0",
      id: 7,
      result: {},
    });
    expect(
      await answer(request("ui/request-display-mode", { mode: "fullscreen" }), context, actions()),
    ).toMatchObject({ result: { mode: "inline" } });
  });

  it("relays a tool call and returns the server's result as it is", async () => {
    const callTool = vi.fn().mockResolvedValue({ structuredContent: { rows: [] }, isError: false });
    const reply = await answer(
      request("tools/call", { name: "widget_data", arguments: { widget_id: "w1" } }),
      context,
      actions({ callTool }),
    );

    expect(callTool).toHaveBeenCalledWith("widget_data", { widget_id: "w1" });
    expect(reply).toMatchObject({ result: { structuredContent: { rows: [] } } });
  });

  it("passes the console's refusal of a tool call on to the page", async () => {
    const callTool = vi
      .fn()
      .mockRejectedValue(
        new ApiError(403, "This page may not use that tool", "AUTHORIZATION_ERROR"),
      );
    const reply = await answer(
      request("tools/call", { name: "delete_everything" }),
      context,
      actions({ callTool }),
    );

    expect(reply).toEqual({
      jsonrpc: "2.0",
      id: 7,
      error: { code: SERVER_ERROR, message: "This page may not use that tool" },
    });
  });

  it("does not echo what a failed request threw when it was not the console's answer", async () => {
    const callTool = vi.fn().mockRejectedValue(new TypeError("Failed to fetch https://internal"));
    const reply = await answer(
      request("tools/call", { name: "x" }),
      context,
      actions({ callTool }),
    );

    expect(reply).toMatchObject({ error: { code: SERVER_ERROR } });
    expect(JSON.stringify(reply)).not.toContain("internal");
  });

  it("refuses a tool call without a name or with arguments that are not an object", async () => {
    const callTool = vi.fn();
    expect(await answer(request("tools/call", {}), context, actions({ callTool }))).toMatchObject({
      error: { code: INVALID_PARAMS },
    });
    expect(
      await answer(
        request("tools/call", { name: "x", arguments: null }),
        context,
        actions({ callTool }),
      ),
    ).toMatchObject({ error: { code: INVALID_PARAMS } });
    expect(
      await answer(
        request("tools/call", { name: "x", arguments: [1] }),
        context,
        actions({ callTool }),
      ),
    ).toMatchObject({ error: { code: INVALID_PARAMS } });
    expect(callTool).not.toHaveBeenCalled();
  });

  it("relays a resource read, and needs a uri for one", async () => {
    const readResource = vi.fn().mockResolvedValue({ contents: [{ uri: "ui://x" }] });
    expect(
      await answer(
        request("resources/read", { uri: "ui://x" }),
        context,
        actions({ readResource }),
      ),
    ).toMatchObject({ result: { contents: [{ uri: "ui://x" }] } });
    expect(
      await answer(request("resources/read"), context, actions({ readResource })),
    ).toMatchObject({
      error: { code: INVALID_PARAMS },
    });
  });

  it("asks the person about an http(s) link and refuses any other scheme", async () => {
    const openLink = vi.fn();
    expect(
      await answer(
        request("ui/open-link", { url: "https://example.com/a" }),
        context,
        actions({ openLink }),
      ),
    ).toMatchObject({ result: {} });
    expect(openLink).toHaveBeenCalledWith("https://example.com/a");

    expect(
      await answer(
        request("ui/open-link", { url: "javascript:alert(1)" }),
        context,
        actions({ openLink }),
      ),
    ).toMatchObject({ error: { code: INVALID_PARAMS } });
    expect(openLink).toHaveBeenCalledTimes(1);
  });

  it("answers what the host does not offer as not found", async () => {
    for (const method of ["ui/message", "ui/update-model-context", "sampling/createMessage"]) {
      expect(await answer(request(method), context, actions())).toMatchObject({
        error: { code: METHOD_NOT_FOUND },
      });
    }
  });
});

describe("openableUrl", () => {
  it("keeps http and https, and nothing else", () => {
    expect(openableUrl("http://example.com")).toBe("http://example.com/");
    expect(openableUrl("data:text/html,x")).toBeNull();
    expect(openableUrl("not a url")).toBeNull();
    expect(openableUrl(42)).toBeNull();
  });
});
