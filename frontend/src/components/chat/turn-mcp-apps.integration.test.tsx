import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MessagePart } from "@/types";
import { TurnParts } from "./turn-parts";

vi.mock("./tool-call-card", () => ({ ToolCallCard: () => <span>Tool step</span> }));
vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("./mcp-app-frame", () => ({
  TurnMcpApps: ({ calls, saved }: { calls: { id: string }[]; saved: boolean }) =>
    saved && calls.length > 0 ? (
      <div data-testid="mcp-pages">{calls.map((c) => c.id).join(",")}</div>
    ) : null,
}));

const page = {
  resource_uri: "ui://charts/viewer.html",
  tool_input: {},
  result: { content: [], isError: false },
};

const parts: MessagePart[] = [
  {
    id: "dash",
    type: "tool",
    toolCall: {
      id: "dash",
      name: "charts_dashboard_show",
      args: {},
      status: "completed",
      result: "12 widgets",
      mcp_app: page,
    },
  },
  { id: "answer", type: "text", content: "Here is the dashboard." },
];

describe("MCP Apps pages in a turn (#3450)", () => {
  it("come after the answer, once the turn is saved", () => {
    render(<TurnParts parts={parts} isStreaming={false} isUser={false} mcpServers={[]} />);

    const answer = screen.getByText("Here is the dashboard.");
    const pages = screen.getByTestId("mcp-pages");
    expect(pages).toHaveTextContent("dash");
    expect(answer.compareDocumentPosition(pages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("wait while the turn streams", () => {
    render(<TurnParts parts={parts} isStreaming isUser={false} mcpServers={[]} />);

    expect(screen.queryByTestId("mcp-pages")).toBeNull();
  });
});
