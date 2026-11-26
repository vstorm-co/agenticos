import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MessagePart } from "@/types";
import { TurnParts } from "./turn-parts";

vi.mock("./tool-call-card", () => ({ ToolCallCard: () => <span>Browser operation</span> }));
vi.mock("./tool-results/workspace", () => ({
  WorkspaceFileCard: ({ path }: { path: string }) => <span data-produced-file>{path}</span>,
}));
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

it("updates the same browser card when later narrated steps arrive", () => {
  const initial = [
    step("search", "search_tools", "Ignored"),
    text("intro", "Opening the browser."),
    step("open", "browser_open", "Home"),
    text("progress", "I will follow the article."),
  ];
  const view = render(<TurnParts parts={initial} isStreaming isUser={false} mcpServers={[]} />);
  const card = screen.getByRole("link", { name: /Visit site/ });
  const expanded = screen.getAllByRole("button", { name: /Working|Worked/ });
  expect(expanded.every((button) => button.getAttribute("aria-expanded") === "false")).toBe(true);
  view.rerender(
    <TurnParts
      parts={[...initial, step("click", "browser_click", "Article"), text("answer", "Done.")]}
      isStreaming={false}
      isUser={false}
      mcpServers={[]}
    />,
  );
  expect(screen.getAllByRole("link", { name: /Visit site/ })).toHaveLength(1);
  expect(screen.getByRole("link", { name: /Visit site/ })).toBe(card);
  expect(card).toHaveTextContent("Article");
});

it("keeps one produced file card at its first write across narrated edits", async () => {
  const initial = [
    step("write", "write_file", "Written", { path: "report.md" }),
    text("progress", "Reviewing the report."),
  ];
  const view = render(<TurnParts parts={initial} isStreaming isUser={false} mcpServers={[]} />);
  const card = screen.getByText("report.md");
  view.rerender(
    <TurnParts
      parts={[
        ...initial,
        step("edit", "edit_file", "Edited", { path: "report.md" }),
        step("other", "write_file", "Written", { path: "summary.md" }),
        text("answer", "Both files are ready."),
      ]}
      isStreaming={false}
      isUser={false}
      mcpServers={[]}
    />,
  );
  expect(screen.getAllByText("report.md")).toHaveLength(1);
  expect(screen.getByText("report.md")).toBe(card);
  expect(screen.getByText("summary.md")).toBeVisible();
  expect(
    card.compareDocumentPosition(await screen.findByText("Reviewing the report.")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
