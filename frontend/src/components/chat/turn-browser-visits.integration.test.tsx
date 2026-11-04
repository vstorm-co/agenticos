import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MessagePart } from "@/types";
import { TurnParts } from "./turn-parts";

vi.mock("./tool-call-card", () => ({ ToolCallCard: () => <span>Browser operation</span> }));
vi.mock("./visual-panel", () => ({ TurnVisuals: () => null }));
vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

const step = (
  id: string,
  name: string,
  title: string,
  args: Record<string, unknown> = {},
  prefix = "",
): MessagePart => ({
  id,
  type: "tool",
  toolCall: {
    id,
    name,
    args,
    status: "completed",
    result: `${prefix}PAGE: ${title} - https://example.com/page`,
  },
});
const text = (id: string, content: string): MessagePart => ({ id, type: "text", content });

describe("browser cards across a whole answer", () => {
  it("keeps one card across narration and repeated reads, live and after completion", () => {
    const parts = [
      step("open", "browser_open", "Home"),
      text("narration", "I will open the article."),
      step("click", "browser_click", "Article"),
      text("next", "I will read the page again."),
      step("read", "browser_read", "Article"),
      text("answer", "Finished reading."),
    ];
    const { rerender } = render(
      <TurnParts parts={parts} isStreaming isUser={false} mcpServers={[]} />,
    );
    expect(screen.getAllByRole("link", { name: /Visit site/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Visit site/ })).toHaveTextContent("Article");
    rerender(<TurnParts parts={parts} isStreaming={false} isUser={false} mcpServers={[]} />);
    expect(screen.getAllByRole("link", { name: /Visit site/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Visit site/ })).toHaveTextContent("Article");
  });

  it("keeps two cards for actual tabs rather than for repeated navigation", () => {
    const parts = [
      step("open", "browser_open", "First tab"),
      text("next", "Opening another tab."),
      step("new", "browser_new_tab", "Second tab", {}, "TAB: second\n"),
      step("switch", "browser_switch_tab", "First tab updated", { tab_id: "main" }),
      text("answer", "Read both tabs."),
    ];
    render(<TurnParts parts={parts} isStreaming={false} isUser={false} mcpServers={[]} />);
    expect(screen.getAllByRole("link", { name: /Visit site/ })).toHaveLength(2);
    expect(screen.getByText("First tab updated")).toBeVisible();
    expect(screen.getByText("Second tab")).toBeVisible();
  });
});
