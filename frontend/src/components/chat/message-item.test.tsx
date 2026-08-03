import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageItem } from "./message-item";
import { useAuthStore, useChatStore, useFilePreviewStore } from "@/stores";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import type { Agent } from "@/types/agents";
import type { ChatMessage, ChatMessageFile, ToolCall } from "@/types";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({
    content,
    onCiteClick,
  }: {
    content: string;
    onCiteClick?: (index: number) => void;
  }) => (
    <div data-testid="markdown">
      {content}
      {onCiteClick ? (
        <button type="button" onClick={() => onCiteClick(2)}>
          cite 2
        </button>
      ) : null}
    </div>
  ),
}));
// The card is tested on its own; here it only needs to be identifiable.
vi.mock("./tool-call-card", () => ({
  ToolCallCard: ({ toolCall }: { toolCall: ToolCall }) => (
    <div data-testid={`tool-${toolCall.id}`}>{toolCall.name}</div>
  ),
}));
// Ratings own their own fetch; this file cares only that they are offered.
vi.mock("./rating-buttons", () => ({
  RatingButtons: ({
    isAssistant,
    onRatingChange,
  }: {
    isAssistant: boolean;
    onRatingChange?: (data: { rating: number; rating_count: unknown }) => void;
  }) =>
    isAssistant ? (
      <button
        type="button"
        onClick={() => onRatingChange?.({ rating: 1, rating_count: { likes: 1, dislikes: 0 } })}
      >
        rate
      </button>
    ) : null,
}));

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "Refunds run to thirty days.",
    timestamp: new Date("2026-07-31T12:00:00Z"),
    ...overrides,
  };
}

function file(overrides: Partial<ChatMessageFile> = {}): ChatMessageFile {
  return {
    id: "f-1",
    filename: "invoice.pdf",
    mime_type: "application/pdf",
    file_type: "pdf",
    ...overrides,
  };
}

function item(
  overrides: Partial<ChatMessage> = {},
  props: {
    agent?: Agent;
    onRegenerate?: () => void;
    groupPosition?: "first" | "middle" | "last" | "single";
  } = {},
) {
  return render(<MessageItem message={message(overrides)} {...props} />);
}

beforeEach(() => {
  useChatStore.setState({ messages: [], isStreaming: false });
  useFilePreviewStore.getState().close();
  useSourcesPanelStore.getState().close();
  useAuthStore.setState({ user: null, avatarVersion: 0 });
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

/**
 * One turn in the transcript.
 *
 * The rule that shapes most of this: a turn is rendered from its *parts* when it
 * has any, and from the flat fields when it does not. Both shapes exist at once -
 * the live stream builds parts, and a conversation saved before parts existed has
 * only `content` and `toolCalls` - so a reader of an old thread and a watcher of a
 * live one have to see the same thing.
 *
 * Attribution is per turn, not per thread. A conversation that switched agents
 * mid-way says so, with the version that answered, because "why did it say that"
 * is a question about one frozen spec rather than about the agent as it is now.
 */
describe("a turn in the transcript", () => {
  it("renders an answer as Markdown and a question as plain text", () => {
    const { unmount } = item();
    expect(screen.getByTestId("markdown")).toHaveTextContent("Refunds run to thirty days.");
    unmount();

    item({ role: "user", content: "How long?" });
    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("How long?")).toBeInTheDocument();
  });

  it("names the agent that answered, and the version that did", () => {
    // Not the agent selected now: a thread that switched agents has to say which
    // one produced which turn.
    item({ agentVersion: 3 }, { agent: { id: "a-1", name: "Support" } as Agent });

    expect(screen.getByText(/Support/)).toBeInTheDocument();
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("names the agent without a version when the transcript recorded none", () => {
    item({}, { agent: { id: "a-1", name: "Support" } as Agent });

    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(/v\d/)).toBeNull();
  });

  it("says nothing about an agent on a person's own message", () => {
    item({ role: "user" }, { agent: { id: "a-1", name: "Support" } as Agent });

    expect(screen.queryByText("Support")).toBeNull();
  });

  it("says it is thinking until anything arrives", () => {
    // An empty bubble reads as an answer of nothing.
    item({ content: "", isStreaming: true });

    expect(screen.getByRole("status")).toHaveTextContent("Thinking...");
  });

  it("stops saying so as soon as a tool call lands", () => {
    item({
      content: "",
      isStreaming: true,
      toolCalls: [{ id: "tc-1", name: "search_documents", args: {}, status: "running" }],
    });

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByTestId("tool-tc-1")).toBeInTheDocument();
  });

  it("stops saying so as soon as a part lands", () => {
    item({
      content: "",
      isStreaming: true,
      parts: [{ id: "p-1", type: "text", content: "Refunds" }],
    });

    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("the ordered timeline", () => {
  it("renders each part in the order it arrived", () => {
    // Reasoning, then the tool it led to, then the answer. Rendering them by kind
    // instead of by arrival would put the answer above the work behind it.
    const { container } = item({
      parts: [
        { id: "p-1", type: "thinking", content: "Check the handbook." },
        {
          id: "p-2",
          type: "tool",
          toolCall: { id: "tc-1", name: "search_documents", args: {}, status: "completed" },
        },
        { id: "p-3", type: "text", content: "Thirty days." },
      ],
    });

    const rendered = Array.from(container.querySelectorAll("details, [data-testid]")).map((node) =>
      node.tagName === "DETAILS" ? "thinking" : node.getAttribute("data-testid"),
    );
    expect(rendered).toEqual(["thinking", "tool-tc-1", "markdown"]);
  });

  it("opens the reasoning while it is the part being written, and closes it after", () => {
    // A thinking block left open on every past turn buries the answers.
    const parts: ChatMessage["parts"] = [{ id: "p-1", type: "thinking", content: "Checking." }];
    const { container, unmount } = item({ parts, isStreaming: true, content: "" });
    expect(container.querySelector("details")).toHaveAttribute("open");
    unmount();

    const closed = item({ parts, isStreaming: false });
    expect(closed.container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("leaves the reasoning closed once something newer is streaming", () => {
    const { container } = item({
      isStreaming: true,
      content: "",
      parts: [
        { id: "p-1", type: "thinking", content: "Checking." },
        { id: "p-2", type: "text", content: "Thirty" },
      ],
    });

    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("shows a cursor on the part being written, and on no other", () => {
    const { container } = item({
      isStreaming: true,
      parts: [
        { id: "p-1", type: "text", content: "First." },
        { id: "p-2", type: "text", content: "Second" },
      ],
    });

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(1);
  });

  it("skips a part with nothing in it yet", () => {
    // The store creates a part before its first delta arrives.
    const { container } = item({
      parts: [
        { id: "p-1", type: "thinking", content: "" },
        { id: "p-2", type: "text", content: "" },
        { id: "p-3", type: "tool" },
      ],
    });

    expect(container.querySelector("details")).toBeNull();
    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("falls back to the flat fields for a conversation saved before parts existed", () => {
    // A replayed old thread has `thinking`, `content` and `toolCalls` and no parts
    // at all.
    const { container } = item({
      thinking: "Checked the handbook.",
      content: "Thirty days.",
      toolCalls: [{ id: "tc-1", name: "search_documents", args: {}, status: "completed" }],
    });

    expect(container.querySelector("details")).toBeInTheDocument();
    expect(screen.getByTestId("markdown")).toHaveTextContent("Thirty days.");
    expect(screen.getByTestId("tool-tc-1")).toBeInTheDocument();
  });

  it("shows no reasoning block on a person's own message that happens to carry one", () => {
    item({ role: "user", thinking: "should not show", content: "How long?" });

    expect(screen.queryByText("should not show")).toBeNull();
  });
});

describe("citations", () => {
  const withSources = {
    toolCalls: [
      {
        id: "tc-1",
        name: "search_documents",
        args: {},
        status: "completed" as const,
        result:
          "[1] Source: handbook.pdf (score: 0.8)\nRefunds.\n[2] Source: policy.md (score: 0.4)\nGift cards.",
      },
    ],
  };

  it("counts the sources behind an answer", () => {
    item({ ...withSources });

    expect(screen.getByRole("button", { name: /2 sources/ })).toBeInTheDocument();
  });

  it("uses the singular for one source", () => {
    item({
      toolCalls: [
        {
          id: "tc-1",
          name: "search_documents",
          args: {},
          status: "completed",
          result: "[1] Source: a.md (score: 0.8)\nOne.",
        },
      ],
    });

    expect(screen.getByRole("button", { name: /1 source/ })).toBeInTheDocument();
  });

  it("marks which kinds of source an answer drew on", async () => {
    // Two small icons rather than a sentence: a reader scanning a thread wants to
    // know whether an answer came from their own documents or from the web.
    const { container } = item({
      toolCalls: [
        {
          id: "tc-1",
          name: "search_documents",
          args: {},
          status: "completed",
          result: "[1] Source: a.md (score: 0.8)\nOne.",
        },
        {
          id: "tc-2",
          name: "web_search",
          args: {},
          status: "completed",
          result: JSON.stringify({
            kind: "web_search",
            results: [{ title: "Hit", url: "https://a.example/" }],
          }),
        },
      ],
    });

    const footer = screen.getByRole("button", { name: /2 sources/ });
    expect(footer.querySelectorAll(".lucide-file-text")).toHaveLength(1);
    expect(footer.querySelectorAll(".lucide-globe")).toHaveLength(1);
    expect(container.querySelector(".lucide-file-text")).not.toBeNull();
  });

  it("shows only the web icon for an answer that came only from the web", () => {
    const { container } = item({
      toolCalls: [
        {
          id: "tc-1",
          name: "web_search",
          args: {},
          status: "completed",
          result: JSON.stringify({
            kind: "web_search",
            results: [{ title: "Hit", url: "https://a.example/" }],
          }),
        },
      ],
    });

    expect(container.querySelectorAll(".lucide-globe")).toHaveLength(1);
  });

  it("opens the whole list from the footer, with nothing highlighted", async () => {
    item({ ...withSources });

    await userEvent.click(screen.getByRole("button", { name: /2 sources/ }));

    expect(useSourcesPanelStore.getState().isOpen).toBe(true);
    expect(useSourcesPanelStore.getState().highlightedIndex).toBeNull();
  });

  it("opens on the citation that was clicked in the answer", async () => {
    // The point of the inline badge: it lands on the passage it refers to.
    item({ ...withSources });

    await userEvent.click(screen.getByRole("button", { name: "cite 2" }));

    expect(useSourcesPanelStore.getState().highlightedIndex).toBe(2);
  });

  it("offers no citations while the answer is still arriving", () => {
    // The list is not final until the turn is.
    item({ ...withSources, isStreaming: true });

    expect(screen.queryByRole("button", { name: /sources/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "cite 2" })).toBeNull();
  });

  it("offers nothing for an answer with no sources", () => {
    item();

    expect(screen.queryByRole("button", { name: /source/ })).toBeNull();
  });
});

describe("what a person attached", () => {
  it("shows an image inline, and opens it in the preview", async () => {
    item({
      role: "user",
      content: "See this",
      files: [file({ filename: "logo.png", file_type: "image", mime_type: "image/png" })],
    });

    await userEvent.click(screen.getByTitle("Open logo.png"));

    expect(useFilePreviewStore.getState().file?.filename).toBe("logo.png");
  });

  it("treats a file the server did not classify as an image by its MIME type", async () => {
    item({
      role: "user",
      content: "See this",
      files: [file({ filename: "logo.png", file_type: "unknown", mime_type: "image/png" })],
    });

    expect(screen.getByTitle("Open logo.png")).toBeInTheDocument();
  });

  it("shows anything else as a chip that opens the preview", async () => {
    item({ role: "user", content: "See this", files: [file()] });

    await userEvent.click(screen.getByRole("button", { name: /invoice\.pdf/ }));

    expect(useFilePreviewStore.getState().file?.id).toBe("f-1");
  });

  it("names the extension on the chip", () => {
    item({ role: "user", content: "x", files: [file({ filename: "invoice.pdf" })] });

    expect(screen.getByText("pdf")).toBeInTheDocument();
  });

  it("shows a chip with no extension for a file that has none", () => {
    item({ role: "user", content: "x", files: [file({ filename: "Makefile" })] });

    expect(screen.getByText("Makefile")).toBeInTheDocument();
  });

  it("falls back to a link for a legacy attachment with only an id", () => {
    // Older messages stored ids and no metadata; the preview panel needs the
    // metadata, so those open in a tab instead.
    item({ role: "user", content: "x", fileIds: ["f-9"] });

    expect(screen.getByRole("link", { name: /Attached file/ })).toHaveAttribute(
      "href",
      "/api/files/f-9",
    );
  });

  it("shows nothing for a message with no attachments", () => {
    item({ role: "user", content: "x", files: [] });

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows a person's own picture beside their message", () => {
    useAuthStore.setState({
      user: { id: "u-1", email: "k@example.com", avatar_url: "/api/users/avatar/u-1" } as never,
      avatarVersion: 2,
    });

    const { container } = item({ role: "user", content: "x" });

    expect(container.querySelector("img")).toBeInTheDocument();
  });
});

describe("the footer", () => {
  it("stamps the time, offers a copy, and offers a rating", () => {
    item();

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "rate" })).toBeInTheDocument();
  });

  it("offers no rating on a person's own message", () => {
    item({ role: "user", content: "x" });

    expect(screen.queryByRole("button", { name: "rate" })).toBeNull();
  });

  it("writes a rating back into the message it belongs to", async () => {
    // The store is the source of truth for the transcript; a rating that only
    // lived in the button would vanish on the next re-render.
    useChatStore.getState().addMessage(message());
    item();

    await userEvent.click(screen.getByRole("button", { name: "rate" }));

    expect(useChatStore.getState().messages[0]).toMatchObject({
      user_rating: 1,
      rating_count: { likes: 1, dislikes: 0 },
    });
  });

  it("shows no footer at all while the answer is streaming", () => {
    // Copying half an answer, or rating one, is worse than waiting.
    item({ isStreaming: true });

    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "rate" })).toBeNull();
  });

  it("offers a regenerate only where the caller allows one", async () => {
    const onRegenerate = vi.fn();
    const { unmount } = item({}, { onRegenerate });
    await userEvent.click(screen.getByRole("button", { name: "Regenerate response" }));
    expect(onRegenerate).toHaveBeenCalled();
    unmount();

    item();
    expect(screen.queryByRole("button", { name: "Regenerate response" })).toBeNull();
  });

  it("never offers a regenerate on a person's own message", () => {
    item({ role: "user", content: "x" }, { onRegenerate: vi.fn() });

    expect(screen.queryByRole("button", { name: "Regenerate response" })).toBeNull();
  });

  it("shows no footer for a turn that produced no text", () => {
    // A tool-only turn has nothing to copy.
    item({ content: "" });

    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

  it("survives a message with no timestamp", () => {
    item({ timestamp: undefined as unknown as Date });

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });
});

describe("a turn split across several messages", () => {
  it("joins the group visually, and stands a single one alone", () => {
    const { container, unmount } = item({}, { groupPosition: "first" });
    expect(container.querySelector(".ring-2")).not.toBeNull();
    unmount();

    const single = item({}, { groupPosition: "single" });
    expect(single.container.querySelector(".ring-2")).toBeNull();
  });

  it("draws the connector for a middle and a last message too", () => {
    for (const position of ["middle", "last"] as const) {
      const { container, unmount } = item({}, { groupPosition: position });
      expect(container.querySelector(".ring-2"), position).not.toBeNull();
      unmount();
    }
  });

  it("never groups a person's own message", () => {
    const { container } = item({ role: "user", content: "x" }, { groupPosition: "first" });

    expect(container.querySelector(".ring-2")).toBeNull();
  });
});

describe("what a turn cost, under the turn", () => {
  const usage = {
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: 0.0125,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
  };

  it("prices an assistant answer where the answer is", () => {
    item({ usage });

    expect(screen.getByText(/\u21931,200/)).toBeVisible();
    expect(screen.getByText(/\$0\.0125/)).toBeVisible();
  });

  it("says nothing on a reloaded turn, which carries no measurement", () => {
    // Usage is measured when a run finishes and is not stored per message, so
    // absent means "not recorded" - and zeroes would be a claim.
    item({});

    expect(screen.queryByText(/\u2193/)).toBeNull();
  });

  it("never prices a person's own message", () => {
    item({ role: "user", content: "How long do refunds take?", usage });

    expect(screen.queryByText(/\u2193/)).toBeNull();
  });
});
