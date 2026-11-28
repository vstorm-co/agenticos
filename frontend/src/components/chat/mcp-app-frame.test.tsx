import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ToolCall } from "@/types/chat";

const api = vi.hoisted(() => ({
  mcpAppFrameUrl: vi.fn(),
  mcpAppCallTool: vi.fn(),
  mcpAppReadResource: vi.fn(),
}));
vi.mock("@/lib/mcp-apps-api", () => api);

import { McpAppFrame, TurnMcpApps } from "./mcp-app-frame";
import { ConversationVisualsProvider } from "./visual-panel";

const page = {
  resource_uri: "ui://charts/viewer.html",
  tool_input: { source: "asset:1", limit: 5 },
  result: {
    content: [{ type: "text", text: "5 rows" }],
    structuredContent: { rows: [[1]] },
    isError: false,
  },
};

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "call-1",
    name: "charts_data_query",
    args: page.tool_input,
    result: "5 rows",
    status: "completed",
    mcp_app: page,
    ...overrides,
  };
}

function frameOf(): HTMLIFrameElement {
  return document.querySelector("iframe") as HTMLIFrameElement;
}

/** The page saying something to the console, as its own window. */
function say(data: unknown, source: MessageEventSource | null = frameOf().contentWindow) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source }));
  });
}

async function shown() {
  render(<McpAppFrame conversationId="conv-1" call={call()} />);
  await waitFor(() => expect(frameOf()).not.toBeNull());
  return vi.spyOn(frameOf().contentWindow as Window, "postMessage");
}

beforeEach(() => {
  vi.clearAllMocks();
  api.mcpAppFrameUrl.mockResolvedValue(
    "https://content.example.com/api/v1/artifact-content/mcp-app/tok",
  );
});

describe("McpAppFrame", () => {
  it("frames the page from its signed address, under a sandbox with scripts alone", async () => {
    await shown();

    expect(api.mcpAppFrameUrl).toHaveBeenCalledWith("conv-1", "call-1");
    expect(frameOf().getAttribute("src")).toBe(
      "https://content.example.com/api/v1/artifact-content/mcp-app/tok",
    );
    expect(frameOf().getAttribute("sandbox")).toBe("allow-scripts");
    expect(frameOf()).toHaveAccessibleName("Page from charts_data_query");
  });

  it("hands the page the call's input and result once it says it is ready", async () => {
    const posted = await shown();

    say({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} });

    expect(posted).toHaveBeenCalledWith(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/tool-input",
        params: { arguments: page.tool_input },
      },
      "*",
    );
    expect(posted).toHaveBeenCalledWith(
      { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: page.result },
      "*",
    );
  });

  it("listens to its own frame alone", async () => {
    const posted = await shown();

    say({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} }, window);
    say({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "x" } }, null);

    expect(posted).not.toHaveBeenCalled();
    expect(api.mcpAppCallTool).not.toHaveBeenCalled();
  });

  it("relays the page's tool call through the console and answers it", async () => {
    api.mcpAppCallTool.mockResolvedValue({ structuredContent: { value: 3 }, isError: false });
    const posted = await shown();

    say({
      jsonrpc: "2.0",
      id: 9,
      method: "tools/call",
      params: { name: "widget_data", arguments: { w: 1 } },
    });

    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith(
        { jsonrpc: "2.0", id: 9, result: { structuredContent: { value: 3 }, isError: false } },
        "*",
      ),
    );
    expect(api.mcpAppCallTool).toHaveBeenCalledWith("conv-1", "call-1", "widget_data", { w: 1 });
  });

  it("takes the height the page reports, within bounds", async () => {
    await shown();
    const box = frameOf().parentElement as HTMLElement;

    say({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 412.2 } });
    expect(box.style.height).toBe("413px");

    say({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 99999 } });
    expect(box.style.height).toBe("900px");
  });

  it("takes the frame down when the page navigates away", async () => {
    await shown();
    act(() => {
      frameOf().dispatchEvent(new Event("load"));
    });
    expect(document.querySelector("iframe")).not.toBeNull();

    act(() => {
      frameOf().dispatchEvent(new Event("load"));
    });

    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.getByText("This result's page could not be loaded.")).toBeInTheDocument();
  });

  it("takes the frame down when a page introduces itself a second time", async () => {
    await shown();
    say({ jsonrpc: "2.0", id: 1, method: "ui/initialize", params: {} });
    const source = frameOf().contentWindow;

    say({ jsonrpc: "2.0", id: 2, method: "ui/initialize", params: {} }, source);
    say({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "widget_data" } }, source);

    expect(document.querySelector("iframe")).toBeNull();
    expect(api.mcpAppCallTool).not.toHaveBeenCalled();
  });

  it("asks again for an address the turn's row was not saved for yet", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      api.mcpAppFrameUrl
        .mockRejectedValueOnce(new Error("404"))
        .mockResolvedValueOnce("https://content.example.com/api/v1/artifact-content/mcp-app/tok");
      render(<McpAppFrame conversationId="conv-1" call={call()} />);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      await waitFor(() => expect(frameOf()).not.toBeNull());
      expect(api.mcpAppFrameUrl).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("says so when the page cannot be had after asking a few times", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      api.mcpAppFrameUrl.mockRejectedValue(new Error("404"));
      render(<McpAppFrame conversationId="conv-1" call={call()} />);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });

      expect(screen.getByText("This result's page could not be loaded.")).toBeInTheDocument();
      expect(api.mcpAppFrameUrl).toHaveBeenCalledTimes(4);
      expect(document.querySelector("iframe")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("TurnMcpApps", () => {
  function inConversation(children: React.ReactNode, conversationId: string | null = "conv-1") {
    return render(
      <ConversationVisualsProvider messages={[]} conversationId={conversationId}>
        {children}
      </ConversationVisualsProvider>,
    );
  }

  it("waits for the turn to be saved before reading a page", () => {
    inConversation(<TurnMcpApps calls={[call()]} saved={false} />);

    expect(api.mcpAppFrameUrl).not.toHaveBeenCalled();
  });

  it("shows nothing on a surface with no conversation to read from", () => {
    inConversation(<TurnMcpApps calls={[call()]} saved />, null);

    expect(api.mcpAppFrameUrl).not.toHaveBeenCalled();
  });

  it("frames each completed call with a page, and none without", async () => {
    inConversation(
      <TurnMcpApps
        calls={[
          call(),
          call({ id: "call-2", mcp_app: null }),
          call({ id: "call-3", status: "running" }),
        ]}
        saved
      />,
    );

    await waitFor(() => expect(api.mcpAppFrameUrl).toHaveBeenCalledTimes(1));
    expect(api.mcpAppFrameUrl).toHaveBeenCalledWith("conv-1", "call-1");
  });
});
