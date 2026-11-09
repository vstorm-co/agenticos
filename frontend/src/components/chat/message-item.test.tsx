import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageItem } from "./message-item";
import { draftsAsText, draftsOf } from "@/lib/drafts";
import * as motion from "@/lib/motion";
import { foldWork, runsOf } from "./turn-parts";
import { useAuthStore, useChatStore, useFilePreviewStore } from "@/stores";
import { ChatScope } from "@/stores/chat-scope";
import { useWorkingStore } from "@/stores/working-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import type { Agent } from "@/types/agents";
import type { ChatMessage, ChatMessageFile, MessagePart, ToolCall, TurnUsage } from "@/types";

// The MCP connections a step is named from. `MessageItem` reads them once per turn
// and hands them to each step, so a public surface can render the same step without
// a session - the fetch would need one, and a query client to run it in.
vi.mock("@/hooks", () => ({ useMcpToolServers: () => [] }));
vi.mock("@/components/artifacts/artifact-thumbnail", () => ({
  ArtifactThumbnail: ({ title }: { title: string }) => <span>thumbnail of {title}</span>,
}));
vi.mock("@/hooks/use-knowledge-bases", () => ({ useKnowledgeBaseFor: () => () => undefined }));
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
vi.mock("./tool-results/routine", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./tool-results/routine")>();
  return {
    ...actual,
    RoutineResult: ({ routine }: { routine: { id: string } }) => (
      <div data-testid="routine-result">{routine.id}</div>
    ),
  };
});
vi.mock("./tool-call-card", () => ({
  ToolCallCard: ({ toolCall, startOpen }: { toolCall: ToolCall; startOpen?: boolean }) => (
    <div data-testid={`tool-${toolCall.id}`} data-open={String(startOpen === true)}>
      {toolCall.name}
    </div>
  ),
}));
// The shortcuts are tested on their own; here it only matters where they are offered.
vi.mock("./turn-shortcuts", () => ({
  TurnShortcuts: ({ request, agentId }: { request: string; agentId: string | null }) => (
    <div data-testid="turn-shortcuts" data-agent={agentId ?? ""} data-request={request} />
  ),
}));
// What a turn left - memory notes, cards - is tested on its own; here only that
// it sits above the time and actions, named by the agent that answered.
vi.mock("./turn-extras", () => ({
  // Nothing for an unnamed agent, as the real one draws nothing for a turn that
  // left nothing - so the tests about the answer's own parts are not about it.
  TurnExtras: ({ agentName }: { agentName?: string }) =>
    agentName ? <div data-testid="turn-extras" data-agent={agentName} /> : null,
}));
vi.mock("./skill-shortcut", () => ({
  SkillShortcut: ({ request, answer }: { request: string; answer: string }) => (
    <div data-testid="skill-shortcut" data-request={request} data-answer={answer} />
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
    onFork?: (messageId: string) => void;
    groupPosition?: "first" | "middle" | "last" | "single";
    continuesTurn?: boolean;
    endsTurn?: boolean;
    turnUsage?: TurnUsage;
    pins?: { pinned: readonly string[]; toggle: (prompt: string) => void };
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
/** What the store has open, resolved through the set the container publishes. */
function openedFile() {
  const state = useFilePreviewStore.getState();
  return state.available.find((one) => one.id === state.openId);
}

describe("a turn in the transcript", () => {
  it("marks an answer whose run was stopped part-way through", () => {
    // A cancelled run leaves whatever had been written when the socket closed,
    // and that reads exactly like a finished answer - so a reader takes a
    // truncated one as everything the agent had to say.
    item({ role: "assistant", content: "The refund window is", wasStopped: true });

    expect(screen.getByText("stopped")).toBeVisible();
  });

  it("marks a turn spoken in a call, and an answer the caller talked over", () => {
    item({
      role: "assistant",
      content: "Tomorrow in Warsaw",
      turnId: "c1:2:assistant",
      interrupted: true,
    });

    expect(screen.getByText("Voice")).toBeVisible();
    expect(screen.getByText("Interrupted")).toHaveAttribute(
      "title",
      "Cut to roughly what was heard",
    );
  });

  it("says nothing about a turn that finished", () => {
    item({ role: "assistant", content: "Refunds run to thirty days." });

    expect(screen.queryByText("stopped")).toBeNull();
    expect(screen.queryByText("Voice")).toBeNull();
  });

  it("marks a stopped ask-only turn, whose only body is the answered question", () => {
    // Stopped after answering a question and before any text: content is empty
    // and the timeline is just the ask_user part, so the footer must key on the
    // parts, not on content, or the stopped indicator vanishes (#502).
    item({
      role: "assistant",
      content: "",
      wasStopped: true,
      parts: [{ id: "q-1", type: "ask_user", question: "Which region?", answer: "eu-west-1" }],
    });

    expect(screen.getByText("stopped")).toBeVisible();
  });

  it("never marks the question, only the answer", () => {
    // A user's turn is not produced by a run; a marker there would attribute the
    // agent's failure to what somebody typed.
    item({ role: "user", content: "How long?", wasStopped: true });

    expect(screen.queryByText("stopped")).toBeNull();
  });

  it("shows what a question pointed the agent at as chips above it (#2189)", () => {
    item({
      role: "user",
      content: "Find the brief",
      mentions: [{ kind: "skill", id: "s-1", name: "refund-policy" }],
    });
    expect(screen.getByTitle("refund-policy")).toHaveTextContent("refund-policy");
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });

  it("renders an answer as Markdown and a question as plain text", () => {
    const { unmount } = item();
    expect(screen.getByTestId("markdown")).toHaveTextContent("Refunds run to thirty days.");
    unmount();

    item({ role: "user", content: "How long?" });
    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("How long?")).toBeInTheDocument();
  });

  it("lets the test panel pin a question, and unpin it, from the question itself (#2075)", () => {
    const toggle = vi.fn();
    const { unmount } = item(
      { role: "user", content: "Refunds?" },
      { pins: { pinned: [], toggle } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Pin to ask again after each change" }));
    unmount();

    item({ role: "user", content: "Refunds?" }, { pins: { pinned: ["Refunds?"], toggle } });
    fireEvent.click(screen.getByRole("button", { name: "Unpin this question" }));
    expect(toggle.mock.calls).toEqual([["Refunds?"], ["Refunds?"]]);
  });

  it("offers no pin outside the test panel, nor on an answer", () => {
    item({ role: "user", content: "Refunds?" });
    expect(screen.queryByRole("button", { name: /Pin to ask again/ })).toBeNull();
  });

  it("puts what the turn left under the answer and above its time and actions", () => {
    item(
      { content: "Here they are", timestamp: new Date() },
      { agent: { id: "a-1", slug: "support", name: "Support" } as Agent },
    );

    const extras = screen.getByTestId("turn-extras");
    expect(extras).toHaveAttribute("data-agent", "Support");
    const time = screen.getByRole("button", { name: "rate" });
    // Before the footer in the document: read with the answer, not after its receipt.
    expect(extras.compareDocumentPosition(time) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("offers to keep a person's request, but not an answer, nor in the test panel", () => {
    const { rerender } = item(
      { role: "user", content: "Refunds?" },
      { agent: { id: "a-1", slug: "support", name: "Support" } as Agent },
    );
    expect(screen.getByTestId("turn-shortcuts")).toHaveAttribute("data-agent", "a-1");
    expect(screen.getByTestId("turn-shortcuts")).toHaveAttribute("data-request", "Refunds?");

    rerender(<MessageItem message={message({ content: "Here they are" })} />);
    expect(screen.queryByTestId("turn-shortcuts")).toBeNull();

    rerender(
      <MessageItem
        message={message({ role: "user", content: "Refunds?" })}
        pins={{ pinned: [], toggle: vi.fn() }}
      />,
    );
    expect(screen.queryByTestId("turn-shortcuts")).toBeNull();
  });

  it("offers to make a skill of a finished answer it was handed the request for", () => {
    const { rerender } = render(
      <MessageItem message={message({ content: "Here they are" })} request="Refunds?" />,
    );
    expect(screen.getByTestId("skill-shortcut")).toHaveAttribute("data-request", "Refunds?");
    expect(screen.getByTestId("skill-shortcut")).toHaveAttribute("data-answer", "Here they are");

    rerender(
      <MessageItem
        message={message({ content: "Here they", isStreaming: true })}
        request="Refunds?"
      />,
    );
    expect(screen.queryByTestId("skill-shortcut")).toBeNull();

    rerender(<MessageItem message={message({ content: "Here they are" })} />);
    expect(screen.queryByTestId("skill-shortcut")).toBeNull();
  });

  it("names the agent that answered, and the version that did", () => {
    // Not the agent selected now: a thread that switched agents has to say which
    // one produced which turn.
    item({ agentVersion: 3 }, { agent: { id: "a-1", slug: "support", name: "Support" } as Agent });

    expect(screen.getByText(/Support/)).toBeInTheDocument();
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("names the agent without a version when the transcript recorded none", () => {
    item({}, { agent: { id: "a-1", slug: "support", name: "Support" } as Agent });

    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(/v\d/)).toBeNull();
  });

  it("says nothing about an agent on a person's own message", () => {
    item({ role: "user" }, { agent: { id: "a-1", slug: "support", name: "Support" } as Agent });

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

describe("a turn in the narrow chat beside a page (the Architect, the test panel)", () => {
  const support = { id: "a-1", slug: "support", name: "Support" } as Agent;
  function compact(
    overrides: Partial<ChatMessage> = {},
    props: { agent?: Agent; groupPosition?: "first" | "single"; continuesTurn?: boolean } = {},
  ) {
    return render(
      <ChatScope agentId="a-1">
        <MessageItem message={message(overrides)} {...props} />
      </ChatScope>,
    );
  }

  it("draws what the person sent into the task as their own message, at the narrow size", () => {
    compact({
      parts: [
        { id: "p-1", type: "text", content: "Pulling the numbers." },
        { id: "p-2", type: "steer", content: "use the EU numbers" },
      ],
    });

    expect(screen.getByText("use the EU numbers")).toBeInTheDocument();
    expect(screen.getByText("You").className).toContain("text-xs");
  });

  it("replays a stored question with nothing recorded as asked or answered", () => {
    compact({ parts: [{ id: "p-1", type: "ask_user" }] });

    expect(screen.getByText("Asked you")).toBeInTheDocument();
  });

  it("puts the face and the name on one line above an answer, with its version", () => {
    compact({ agentVersion: 2 }, { agent: support, groupPosition: "first" });

    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.getByText(/v2/)).toBeInTheDocument();
  });

  it("calls an answer by a generic name when the agent is unknown, without a version", () => {
    compact({});

    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.queryByText(/v\d/)).toBeNull();
  });

  it("calls the person's own message theirs", () => {
    compact({ role: "user", content: "Refunds?" }, { agent: support });

    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.queryByText("Support")).toBeNull();
  });

  it("draws no second line for a segment continuing the same turn", () => {
    compact({}, { agent: support, continuesTurn: true });

    expect(screen.queryByText("Support")).toBeNull();
  });
});

describe("the ordered timeline", () => {
  describe("a turn with a draft", () => {
    const write: ToolCall = {
      id: "tc-d",
      name: "write_draft",
      presentation_kind: "draft",
      status: "completed",
      result: "Drafted Reply.",
      args: {
        title: "Reply to Marta",
        kind: "email",
        versions: [{ fields: [{ text: "Hi Marta," }] }],
      },
    };
    const drafted = (result: string): MessagePart[] => [
      { id: "p-1", type: "text", content: "Here's a reply." },
      { id: "p-2", type: "tool", toolCall: { ...write, result } },
      { id: "p-3", type: "text", content: "Want it shorter?" },
    ];

    it("shows the card after the work and before what follows", () => {
      item({ parts: drafted("Drafted Reply.") });

      const before = screen.getByRole("button", { name: /^Worked/ });
      const card = screen.getByText("Reply to Marta");
      const after = screen.getByText("Want it shorter?");
      expect(before.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(card.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getAllByText("Reply to Marta")).toHaveLength(1);
    });

    it("shows no card for a refusal", () => {
      item({ parts: drafted("Each version needs a label.") });

      expect(screen.queryByText("Reply to Marta")).toBeNull();
    });

    it("copies the answer and the draft with the message's own action", async () => {
      item({ content: "Here you go.", toolCalls: [write] });

      // The card's own copy buttons come first; the message's action is last.
      await userEvent.click(screen.getAllByRole("button", { name: "Copy to clipboard" }).at(-1)!);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "Here you go.\n\n" + draftsAsText(draftsOf([write])),
      );
    });

    it("offers the copy action when the draft is all the turn produced", async () => {
      item({ content: "", parts: [{ id: "p-d", type: "tool", toolCall: write }] });

      await userEvent.click(screen.getAllByRole("button", { name: "Copy to clipboard" }).at(-1)!);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(draftsAsText(draftsOf([write])));
    });
  });

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
    // Finished, the work folds into one line above the answer; opened, it is in the
    // order it happened.
    fireEvent.click(screen.getByRole("button", { name: "Worked · 1 step" }));

    // Only the top level: the reasoning renders its own Markdown now, so its mock
    // sits *inside* the `details`. This is about the order of the parts, not of
    // everything they contain.
    const rendered = Array.from(container.querySelectorAll("details, [data-testid]"))
      .filter((node) => node.tagName === "DETAILS" || node.closest("details") === null)
      .map((node) => (node.tagName === "DETAILS" ? "thinking" : node.getAttribute("data-testid")));
    expect(rendered).toEqual(["thinking", "tool-tc-1", "markdown"]);
  });

  it("replays a mid-turn question and its answer as a step in the turn (#502)", () => {
    const { getByText } = item({
      parts: [
        { id: "p-1", type: "text", content: "I need to know first." },
        { id: "p-2", type: "ask_user", question: "Which region?", answer: "eu-west-1" },
        { id: "p-3", type: "text", content: "Deploying." },
      ],
    });

    expect(getByText("Asked you")).toBeInTheDocument();
    expect(getByText("Which region?")).toBeInTheDocument();
    expect(getByText("You answered")).toBeInTheDocument();
    expect(getByText("eu-west-1")).toBeInTheDocument();
  });

  it("shows what the person added mid-run where it landed in the turn (#2087)", () => {
    const { getByText } = item({
      parts: [
        { id: "p-1", type: "text", content: "Pulling the US numbers." },
        { id: "p-2", type: "steer", content: "use the EU numbers" },
        { id: "p-3", type: "text", content: "Switching to the EU numbers." },
      ],
    });

    // As the person's own message, not an aside saying they "added" something.
    expect(screen.queryByText("You added:")).toBeNull();
    expect(getByText("You")).toBeInTheDocument();
    expect(getByText("use the EU numbers")).toBeInTheDocument();
  });

  it("names the delegate that asked, where one did (#1042)", () => {
    // "the deployer asked" and "the agent asked" are different things to read on
    // a replayed turn, and the transcript could not tell them apart.
    const { getByText, queryByText } = item({
      parts: [
        {
          id: "p-1",
          type: "ask_user",
          question: "Which region?",
          answer: "eu-west-1",
          askedBy: "deployer",
        },
      ],
    });

    expect(getByText("Asked by deployer")).toBeInTheDocument();
    expect(queryByText("Asked you")).not.toBeInTheDocument();
  });

  it("keeps live reasoning behind the activity disclosure", () => {
    // A thinking block left open on every past turn buries the answers.
    const parts: ChatMessage["parts"] = [{ id: "p-1", type: "thinking", content: "Checking." }];
    const { container, unmount } = item({ parts, isStreaming: true, content: "" });
    expect(screen.getByRole("button", { name: /Working/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(container.querySelector("details")).not.toHaveAttribute("open");
    unmount();

    const closed = item({ parts, isStreaming: false });
    expect(closed.container.querySelector("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Thought about it" }));
    expect(closed.container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("keeps answered questions collapsed until the reader expands one", async () => {
    const { container } = item({
      parts: [{ id: "q", type: "ask_user", question: "Which team?", answer: "Engineering" }],
    });
    expect(container.querySelector("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Engineering")).not.toBeVisible();
    await userEvent.click(screen.getByText("Asked you"));
    expect(screen.getByText("Engineering")).toBeVisible();
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

  it("gives the answer a little air after the thinking, and none after a plain line", () => {
    const { getAllByTestId } = item({
      isStreaming: true,
      parts: [
        { id: "p-1", type: "thinking", content: "Checking." },
        { id: "p-2", type: "text", content: "Answer." },
        { id: "p-3", type: "text", content: "More." },
      ],
    });

    const [answer, more] = getAllByTestId("markdown")
      .slice(-2)
      .map((node) => node.parentElement!);
    expect(answer!.className).toContain("pt-1");
    expect(more!.className).not.toContain("pt-1");
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
    // Two of them: the reasoning is Markdown as well as the answer. The answer is
    // the one outside the `details`.
    const answer = Array.from(container.querySelectorAll('[data-testid="markdown"]')).find(
      (node) => node.closest("details") === null,
    );
    expect(answer).toHaveTextContent("Thirty days.");
    expect(screen.getByTestId("tool-tc-1")).toBeInTheDocument();
  });

  it("shows no reasoning block on a person's own message that happens to carry one", () => {
    item({ role: "user", thinking: "should not show", content: "How long?" });

    expect(screen.queryByText("should not show")).toBeNull();
  });
});

describe("an app the turn published", () => {
  const publishing = {
    toolCalls: [
      {
        id: "tc-1",
        name: "publish_artifact",
        args: {},
        status: "completed" as const,
        result: JSON.stringify({
          kind: "artifact",
          artifact_id: "app-1",
          version_id: "v-2",
          version: 2,
          title: "Revenue dashboard",
        }),
      },
    ],
  };

  it("is a card under the answer, opening the version this turn wrote", () => {
    item(publishing);

    const card = screen.getByRole("link", { name: /Revenue dashboard/ });
    expect(card).toHaveAttribute("href", "/apps/app-1?version=v-2");
  });

  it("shows an already published app while the parent continues", () => {
    item({ ...publishing, isStreaming: true });

    expect(screen.getByRole("link", { name: /Revenue dashboard/ })).toBeVisible();
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

  it("stacks a mark for each document an answer drew on, by its kind", () => {
    // A file's kind for a knowledge base passage, the site's favicon for a page:
    // a reader scanning a thread sees where an answer came from without opening it.
    item({
      toolCalls: [
        {
          id: "tc-1",
          name: "search_documents",
          args: {},
          status: "completed",
          result: "[1] Source: a.md (score: 0.8)\nOne.\n[2] Source: a.md (score: 0.7)\nTwo.",
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

    // Two passages of one file are one source.
    const footer = screen.getByRole("button", { name: /2 sources/ });
    expect(footer.querySelector("img")).toHaveAttribute("src", "https://a.example/favicon.ico");
    expect(footer.querySelectorAll("svg")).toHaveLength(2);
  });

  it("opens the source panel directly from the compact footer", async () => {
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

    expect(openedFile()?.filename).toBe("logo.png");
  });

  it("treats a file the server did not classify as an image by its MIME type", async () => {
    item({
      role: "user",
      content: "See this",
      files: [file({ filename: "logo.png", file_type: "unknown", mime_type: "image/png" })],
    });

    expect(screen.getByTitle("Open logo.png")).toBeInTheDocument();
  });

  it("shows a TIFF as a file card, not an inline thumbnail", async () => {
    // A TIFF has `file_type: "image"` and `mime_type: "image/tiff"`, but no browser
    // draws it inline, so it must be a card whose src is not the download URL (#1591).
    item({
      role: "user",
      content: "See this",
      files: [file({ filename: "scan.tiff", file_type: "image", mime_type: "image/tiff" })],
    });

    // No inline thumbnail; the shared card names it and its type instead.
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("TIFF")).toBeInTheDocument();
  });

  it("shows anything else as a chip that opens the preview", async () => {
    item({ role: "user", content: "See this", files: [file()] });

    await userEvent.click(screen.getByRole("button", { name: /invoice\.pdf/ }));

    expect(openedFile()?.id).toBe("f-1");
  });

  it("names the type on the card", () => {
    item({ role: "user", content: "x", files: [file({ filename: "invoice.pdf" })] });

    // Upper case, as the shared card sets it - the transcript used to draw its own
    // pill, so one file read three ways on one screen.
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });

  it("shows a chip with no extension for a file that has none", () => {
    item({ role: "user", content: "x", files: [file({ filename: "Makefile" })] });

    expect(screen.getByText("Makefile")).toBeInTheDocument();
  });

  it("calls a long paste what it was, not the name invented for it", () => {
    item({
      role: "user",
      content: "x",
      files: [
        file({ filename: "pasted-2026-10-12.txt", mime_type: "text/plain", file_type: "text" }),
      ],
    });

    expect(screen.getByText("Pasted")).toBeInTheDocument();
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

  it("keeps readable initials beside a message while its picture loads or fails", () => {
    // jsdom never loads an image, which is what a missing file looks like: a
    // bare <img> left an empty circle there (#2248).
    useAuthStore.setState({
      user: {
        id: "u-1",
        full_name: "Kacper W",
        email: "k@example.com",
        avatar_url: "/api/users/avatar/u-1",
      } as never,
      avatarVersion: 2,
    });

    item({ role: "user", content: "x" });

    expect(screen.getByText("KW")).toBeVisible();
  });

  it("draws initials for a person who uploaded no picture", () => {
    useAuthStore.setState({
      user: { id: "u-1", full_name: "Kacper W", email: "k@example.com" } as never,
    });

    item({ role: "user", content: "x" });

    expect(screen.getByText("KW")).toBeVisible();
  });

  it("names a teammate's turn in a project's chat by them, not as You", () => {
    useAuthStore.setState({ user: { id: "u-1", email: "k@example.com" } as never });
    const anna = { user_id: "u-2", name: "Anna", has_avatar: false, avatar_color: null };

    const { unmount } = item({ role: "user", content: "picking this up", sender: anna });
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.queryByText("You")).toBeNull();
    unmount();

    // The reader's own turn, signed with their own id, is still theirs.
    item({ role: "user", content: "x", sender: { ...anna, user_id: "u-1", name: "Kacper" } });
    expect(screen.getByText("You")).toBeInTheDocument();
  });

  it("offers Reply on a stored message, and quotes what a reply answers", async () => {
    useAuthStore.setState({ user: { id: "u-1", email: "k@example.com" } as never });
    const { unmount } = item({
      id: "m-2",
      role: "assistant",
      content: "Plan:\n step one",
      conversationId: "c-1",
    });
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    expect(useChatStore.getState().replyTo).toEqual({
      messageId: "m-2",
      role: "assistant",
      excerpt: "Plan: step one",
      sender: undefined,
      agentId: undefined,
      agentName: undefined,
    });
    unmount();

    item({
      role: "user",
      content: "bigger",
      isTemporaryId: true,
      replyTo: { messageId: "m-2", role: "assistant", excerpt: "Plan: step one" },
    });
    expect(screen.getByText("Plan: step one")).toBeInTheDocument();
    // Its own id is this tab's: nothing can be addressed to it yet.
    expect(screen.queryByRole("button", { name: "Reply" })).toBeNull();
  });

  it("keeps the quote on a file-only reply with no message text", () => {
    item({
      role: "user",
      content: "",
      replyTo: { messageId: "source", role: "assistant", excerpt: "Please attach the file." },
    });
    expect(screen.getByText("Please attach the file.")).toBeVisible();
  });

  it("draws a turn whose writer has left as a former member, never as You", () => {
    useAuthStore.setState({ user: { id: "u-1", email: "k@example.com" } as never });

    item({ role: "user", content: "an old idea", senderGone: true });

    expect(screen.getByText("A former member")).toBeInTheDocument();
    expect(screen.queryByText("You")).toBeNull();
  });

  it("draws the agent's face mid-thought while the turn is still streaming", () => {
    // The one picture in the product that says an agent is still working, which
    // is why it is worth the inline SVG the motion costs.
    const { container } = item(
      { isStreaming: true },
      { agent: { id: "a-1", slug: "support", name: "Support" } as Agent },
    );

    // The expression class, which is the half that only a turn in flight adds.
    expect(container.querySelector("g.mo-expr")).toBeInTheDocument();
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

  it("offers no rating on an answer the server never saved", () => {
    // A turn that failed before `message_saved` keeps its client id, which the
    // rating endpoint answers with "Message not found".
    item({ isTemporaryId: true });

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

  it("offers a fork of a saved answer where the caller may fork", async () => {
    const onFork = vi.fn();
    const { unmount } = item({ id: "m-9" }, { onFork });
    await userEvent.click(screen.getByRole("button", { name: "Fork into a new conversation" }));
    expect(onFork).toHaveBeenCalledWith("m-9");
    unmount();

    // Not the owner's thread: the container passes no handler.
    item();
    expect(screen.queryByRole("button", { name: "Fork into a new conversation" })).toBeNull();
  });

  it("never offers a fork of a person's message, a system note or an answer not yet saved", () => {
    const { unmount } = item({ role: "user", content: "x" }, { onFork: vi.fn() });
    expect(screen.queryByRole("button", { name: "Fork into a new conversation" })).toBeNull();
    unmount();

    const system = item({ role: "system", content: "x" }, { onFork: vi.fn() });
    expect(screen.queryByRole("button", { name: "Fork into a new conversation" })).toBeNull();
    system.unmount();

    item({ isTemporaryId: true }, { onFork: vi.fn() });
    expect(screen.queryByRole("button", { name: "Fork into a new conversation" })).toBeNull();
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
  it("sits its parts closer together than two separate turns", () => {
    const { container, unmount } = item({}, { groupPosition: "middle" });
    expect(container.querySelector("[data-message-id]")).toHaveClass("pt-2");
    unmount();

    const single = item({}, { groupPosition: "single" });
    expect(single.container.querySelector("[data-message-id]")).toHaveClass("pt-3");
  });
});

describe("what a turn cost, under the turn", () => {
  const usage = {
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: "0.0125",
    cost_is_partial: false,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    context: null,
  };

  it("prices an assistant answer where the answer is", () => {
    item({ usage });

    // Rounded to the cent, the exact figure on hover, and no token counts.
    expect(screen.getByText("$0.01")).toHaveAttribute("title", "$0.0125");
    expect(screen.queryByText(/\u2193/)).toBeNull();
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

/**
 * How a turn's parts become stretches of work.
 *
 * The grouping is what makes consecutive tool calls read as one thread rather than a
 * dashed line of separately bordered rows - and what a part of any other kind closes,
 * because the agent said something and what follows is new work.
 */
describe("the runs a turn is made of", () => {
  const tool = (id: string) => ({
    id,
    type: "tool" as const,
    toolCall: { id: `tc-${id}`, name: "ls", args: {}, status: "completed" as const },
  });

  it("gathers consecutive tool calls into one run", () => {
    const runs = runsOf([tool("a"), tool("b"), tool("c")]);

    expect(runs).toHaveLength(1);
    const [run] = runs;
    expect(run?.kind === "tools" && run.parts).toHaveLength(3);
    expect(run?.isLast).toBe(true);
  });

  it("closes a run when the agent says something", () => {
    const runs = runsOf([tool("a"), { id: "t1", type: "text", content: "Done." }, tool("b")]);

    expect(runs.map((run) => run.kind)).toEqual(["tools", "other", "tools"]);
    expect(runs.at(-1)?.isLast).toBe(true);
  });

  it("leaves out a call drawn under the answer instead, without splitting the run around it", () => {
    const offer = {
      id: "s",
      type: "tool" as const,
      toolCall: { id: "tc-s", name: "suggest_next_steps", args: {}, status: "completed" as const },
    };
    const runs = runsOf([tool("a"), offer, tool("b")]);

    expect(runs).toHaveLength(1);
    expect(runs[0]?.kind === "tools" && runs[0].parts.map((part) => part.id)).toEqual(["a", "b"]);
  });

  it("drops an empty text or thinking part rather than drawing an empty bubble", () => {
    expect(runsOf([{ id: "t1", type: "text", content: "" }])).toEqual([]);
    expect(runsOf([{ id: "t2", type: "thinking" }])).toEqual([]);
    expect(runsOf([])).toEqual([]);
  });

  it("keeps a steer as its own run and drops an empty one (#2087)", () => {
    const runs = runsOf([
      { id: "s1", type: "steer", content: "shorter" },
      { id: "s2", type: "steer", content: "" },
    ]);

    expect(runs).toHaveLength(1);
    expect(runs[0]?.kind === "other" && runs[0].part.type).toBe("steer");
  });

  it("keeps an ask_user part as its own run, empty content notwithstanding (#502)", () => {
    const runs = runsOf([
      { id: "q1", type: "ask_user", question: "Which region?", answer: "eu-west-1" },
    ]);

    expect(runs).toHaveLength(1);
    const [run] = runs;
    expect(run?.kind === "other" && run.part.type).toBe("ask_user");
    expect(run?.isLast).toBe(true);
  });
});

/**
 * Which step is open when a conversation is reopened.
 *
 * `openLastStep` is set for one turn - the last that used a tool, see
 * `lastToolTurnIndex` - and inside it exactly one step opens: the last of the last run.
 * Opening every finished call turned a reopened thread into a wall of results; opening
 * none of them hid the thing that had just been asked for.
 */
describe("the step a reopened turn leaves open", () => {
  const toolPart = (id: string) => ({
    id: `p-${id}`,
    type: "tool" as const,
    toolCall: { id: `tc-${id}`, name: "ls", args: {}, status: "completed" as const },
  });

  it("opens the run's last step and leaves the ones before it closed", () => {
    render(
      <MessageItem message={message({ parts: [toolPart("a"), toolPart("b")] })} openLastStep />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Worked · 2 steps" }));
    expect(screen.getByTestId("tool-tc-a")).toHaveAttribute("data-open", "false");
    expect(screen.getByTestId("tool-tc-b")).toHaveAttribute("data-open", "true");
  });

  it("opens nothing in a run the agent has already answered after", () => {
    // The reader's eye belongs on the answer, not on the listing that led to it.
    render(
      <MessageItem
        message={message({ parts: [toolPart("a"), { id: "p-t", type: "text", content: "Done." }] })}
        openLastStep
      />,
    );

    expect(screen.queryByTestId("tool-tc-a")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Worked · 1 step" }));
    expect(screen.getByTestId("tool-tc-a")).toHaveAttribute("data-open", "false");
  });

  it("shows every step on demand through a single live activity disclosure", () => {
    // Folding a run that is still being written hides the step that is happening.
    render(
      <MessageItem
        message={message({ parts: [toolPart("a"), toolPart("b")], isStreaming: true })}
      />,
    );

    expect(screen.getByRole("button", { name: /Working/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByTestId("tool-tc-a")).not.toBeVisible();
    fireEvent.click(screen.getByText("2 actions", { selector: "summary span" }));
    expect(screen.getByTestId("tool-tc-a")).toBeVisible();
    expect(screen.getByTestId("tool-tc-b")).toBeVisible();
  });

  it("opens the last call of a turn saved before parts existed", () => {
    // An old thread has `toolCalls` and no parts, and has to read the same way.
    const calls: ToolCall[] = [
      { id: "old-1", name: "ls", args: {}, status: "completed" },
      { id: "old-2", name: "read_file", args: {}, status: "completed" },
    ];
    render(<MessageItem message={message({ parts: [], toolCalls: calls })} openLastStep />);

    expect(screen.getByTestId("tool-old-1")).toHaveAttribute("data-open", "false");
    expect(screen.getByTestId("tool-old-2")).toHaveAttribute("data-open", "true");
  });
});

describe("a segment that continues the turn above it", () => {
  it("names the agent once, at the top of the turn", () => {
    // A run that parked on an approval leaves several messages. Repeating the
    // avatar and the name on each one read as three agents answering one
    // question - see `continuesTurn` in `MessageList`.
    item(
      {},
      { agent: { id: "a-1", slug: "support", name: "Support" } as Agent, continuesTurn: true },
    );

    expect(screen.queryByText("Support")).toBeNull();
  });

  it("closes the gap below it as well as above, inside one turn", () => {
    // A turn that ran three commands is three segments, each carrying one step.
    // Only the top half was tightened, so they sat a message-gap apart and read
    // as three separate things the agent did rather than one run.
    const { container } = item(
      {},
      {
        agent: { id: "a-1", slug: "support", name: "Support" } as Agent,
        continuesTurn: true,
        endsTurn: false,
      },
    );

    const row = container.firstElementChild!;

    expect(row.className).toContain("pt-0");
    expect(row.className).toContain("pb-0");
    // And no shorthand under them. `py-3 pt-0 pb-0` leaves which utility wins to
    // the order of the generated stylesheet, and the padding survived.
    expect(row.className).not.toMatch(/\bpy-/);
  });

  it("keeps its bottom padding on the segment that ends the turn", () => {
    const { container } = item(
      {},
      {
        agent: { id: "a-1", slug: "support", name: "Support" } as Agent,
        continuesTurn: true,
        endsTurn: true,
      },
    );

    expect(container.firstElementChild!.className).not.toContain("pb-0");
  });

  it("draws no second face or name, so the turn reads as one message", () => {
    const { container } = item(
      {},
      { agent: { id: "a-1", slug: "support", name: "Support" } as Agent, continuesTurn: true },
    );

    // The face and the name head the turn once, over the full-width column, so a
    // segment that continues it starts straight with its content.
    expect(container.querySelector(".rounded-full")).toBeNull();
    expect(screen.queryByText("Support")).toBeNull();
  });
});

describe("the footer of a turn drawn in several messages", () => {
  const USAGE: TurnUsage = {
    input_tokens: 6603,
    output_tokens: 189,
    cost_usd: "0.0133",
    cost_is_partial: false,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    context: null,
  };

  it("says nothing under a segment the turn continues past", () => {
    // The run reports what it has spent when it parks, so this used to put the
    // time, the tokens and the cost halfway up the answer.
    const { unmount } = item({ content: "Waiting.", usage: USAGE }, { endsTurn: false });
    expect(screen.queryByTitle("$0.0133")).toBeNull();
    unmount();

    // The same message where the turn does end, so the absence above is the
    // grouping and not a query that matches nothing.
    item({ content: "Waiting.", usage: USAGE });
    expect(screen.getByTitle("$0.0133")).toBeInTheDocument();
  });

  it("draws the turn's figure under the message that ends it", () => {
    // Recorded on an earlier segment, shown under the last one - one figure for
    // one turn, where the answer actually ends.
    item({ content: "Six sheets." }, { turnUsage: USAGE });

    expect(screen.getByTitle("$0.0133")).toBeInTheDocument();
  });

  it("falls back to its own figure when it is the whole turn", () => {
    item({ content: "Six sheets.", usage: USAGE });

    expect(screen.getByTitle("$0.0133")).toBeInTheDocument();
  });
});

describe("the work before an answer", () => {
  const call = (
    id: string,
    status: ToolCall["status"] = "completed",
    name = "ls",
  ): MessagePart => ({
    id: `p-${id}`,
    type: "tool",
    toolCall: { id: `tc-${id}`, name, args: {}, status },
  });
  const text = (id: string, content: string): MessagePart => ({ id, type: "text", content });
  const thought: MessagePart = { id: "p-th", type: "thinking", content: "Hmm." };

  it("folds the thinking, the calls and the narration into one line above the answer", () => {
    const split = foldWork(
      runsOf([
        thought,
        text("n", "Let me check."),
        call("a"),
        call("b"),
        text("ans", "Thirty days."),
      ]),
    );
    expect(split?.steps).toBe(2);
    expect(split?.folded).toHaveLength(3);
    expect(split?.shown).toHaveLength(1);
  });

  it("folds tool-only work and leaves plain answers alone", () => {
    expect(foldWork(runsOf([call("a")]))).toMatchObject({ steps: 1, shown: [] });
    expect(foldWork(runsOf([text("ans", "Hello.")]))).toBeNull();
    expect(foldWork(runsOf([text("n", "First."), text("ans", "Second.")]))).toBeNull();
  });

  it("keeps long progress, questions and errors in history before the final answer", () => {
    // All progress stays chronological inside the one completed history.
    const long = text("long", "x".repeat(401));
    const asked: MessagePart = { id: "p-q", type: "ask_user", question: "Which?", answer: "A" };
    const steer: MessagePart = { id: "p-s", type: "steer", content: "Also B." };
    const split = foldWork(
      runsOf([call("a"), long, asked, steer, call("bad", "error"), text("ans", "Done.")]),
    );
    expect(split?.steps).toBe(2);
    expect(split?.shown).toHaveLength(1);
    expect(split?.folded).toHaveLength(5);
  });

  it("keeps routine and failed calls in the same live history", () => {
    const split = foldWork(
      runsOf([call("a"), thought, call("b"), call("bad", "error")]),
      false,
      true,
    );
    expect(split?.steps).toBe(3);
    expect(split?.shown).toHaveLength(0);
    expect(split?.folded).toHaveLength(3);
  });

  it("does not show Working above a question that is waiting for an answer", () => {
    item({ parts: [call("question", "awaiting_answer", "ask_user_question")], isStreaming: true });
    expect(screen.queryByText(/Working/)).toBeNull();
    expect(screen.getByTestId("tool-tc-question")).toBeVisible();
    expect(screen.getByRole("button", { name: /Waiting for an answer/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("does not settle a turn while a delegate still needs approval", () => {
    item({
      parts: [text("progress", "Waiting for the specialist."), call("delegate")],
      isStreaming: false,
      runWaitingFor: "approval",
    });
    expect(screen.getByRole("button", { name: /Waiting for approval/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Waiting for the specialist.")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Worked/ })).toBeNull();
  });

  it("times a reloaded turn by its run, under its last segment only", () => {
    const parts = [call("a"), text("ans", "Done.")];
    const { unmount } = item({ parts, runDurationMs: 12_400 });
    expect(screen.getByRole("button", { name: "Worked for 12s · 1 step" })).toBeInTheDocument();
    unmount();

    item({ parts, runDurationMs: 12_400 }, { endsTurn: false });
    expect(screen.getByRole("button", { name: "Worked · 1 step" })).toBeInTheDocument();
  });

  it("uses the shared run clock instead of a resumed segment timestamp", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-06T00:03:00Z"));
    useWorkingStore.getState().start("clock-chat", "2026-11-06T00:00:00Z");
    try {
      item({
        conversationId: "clock-chat",
        timestamp: new Date("2026-11-06T00:02:50Z"),
        runStartedAt: new Date("2026-11-06T00:02:50Z"),
        parts: [call("a", "running")],
        isStreaming: true,
      });
      act(() => vi.advanceTimersByTime(1000));
      expect(screen.getByRole("button", { name: /Working for 3m 1s/ })).toBeInTheDocument();
    } finally {
      useWorkingStore.getState().reset();
      vi.useRealTimers();
    }
  });

  it("says the turn is working while it streams, and only once there is work", () => {
    const { unmount } = item({ parts: [call("a", "running")], isStreaming: true });
    expect(screen.getByRole("button", { name: /Working/ })).toBeInTheDocument();
    unmount();

    item({ parts: [text("ans", "Thir")], isStreaming: true });
    expect(screen.queryByText(/Working/)).not.toBeInTheDocument();
  });

  it("keeps failures and pending tools in the same chronological live timeline", async () => {
    item({
      parts: [
        thought,
        call("read"),
        text("n", "Checking permissions."),
        call("bad", "error"),
        call("approve", "awaiting_approval"),
      ],
      isStreaming: true,
    });
    expect(screen.getByText("Checking permissions.")).toBeVisible();
    expect(screen.getByTestId("tool-tc-read")).toBeVisible();
    expect(screen.getByTestId("tool-tc-bad")).not.toBeVisible();
    await userEvent.click(screen.getByText("2 actions", { selector: "summary span" }));
    expect(screen.getByTestId("tool-tc-bad")).toBeVisible();
    expect(screen.getByTestId("tool-tc-approve")).toBeVisible();
    expect(screen.getAllByRole("button", { name: /Waiting for approval/ })).toHaveLength(1);
  });

  it("folds the whole interrupted sequence rather than promoting narration to a final answer", async () => {
    item({
      parts: [
        call("before"),
        text("n", "The board already exists."),
        thought,
        call("after"),
        call("last"),
      ],
    });
    expect(screen.queryByText("The board already exists.")).toBeNull();
    const toggle = screen.getByRole("button", { name: /Worked/ });
    await userEvent.click(toggle);
    expect(screen.getByText("The board already exists.")).toBeVisible();
    expect(screen.getByTestId("tool-tc-before")).toBeVisible();
    expect(screen.getByTestId("tool-tc-after")).not.toBeVisible();
    await userEvent.click(screen.getByText("2 actions", { selector: "summary span" }));
    expect(screen.getByTestId("tool-tc-after")).toBeVisible();
    expect(screen.getByTestId("tool-tc-last")).toBeVisible();
  });

  it("keeps progress messages beside their tools live, then folds everything except the final answer", async () => {
    const parts = [
      text("first", "I will check Poland first."),
      call("poland"),
      text("second", "Now I will compare Norway and Australia."),
      call("norway"),
      call("australia"),
      text("final", "Here is the final comparison."),
    ];
    const view = item({ parts, isStreaming: true });
    const first = screen.getByText("I will check Poland first.");
    const firstTool = screen.getByTestId("tool-tc-poland");
    const second = screen.getByText("Now I will compare Norway and Australia.");
    const secondTool = screen.getByTestId("tool-tc-norway");
    expect(
      first.compareDocumentPosition(firstTool) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      firstTool.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      second.compareDocumentPosition(secondTool) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Working/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    view.rerender(<MessageItem message={message({ parts, isStreaming: false })} />);
    expect(screen.getByText("Here is the final comparison.")).toBeVisible();
    expect(screen.queryByText("I will check Poland first.")).toBeNull();
    const toggle = screen.getByRole("button", { name: /Worked/ });
    expect(screen.getAllByRole("button", { name: /Worked/ })).toHaveLength(1);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByText("I will check Poland first.")).toBeVisible();
    expect(screen.getByTestId("tool-tc-poland")).toBeVisible();
    expect(screen.getByText("Here is the final comparison.").closest('[role="region"]')).toBeNull();
  });

  it("does not interpret headings in reasoning as process steps", async () => {
    item({
      parts: [
        {
          id: "reason",
          type: "thinking",
          content: "**Investigating project details**\nRead the instructions.",
        },
        call("read"),
        text("final", "Ready."),
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: /Worked/ }));
    expect(screen.getByText("Thought about it")).toBeVisible();
    expect(screen.getByTestId("tool-tc-read")).toBeVisible();
    expect(screen.queryByText("Investigating project details")).toBeNull();
  });

  it("folds a stopped turn's work into one line that says it stopped, with no Done", () => {
    const parts = [call("a"), call("b")];
    item({ parts, runDurationMs: 12_400, wasStopped: true });

    expect(screen.getByRole("button", { name: "Stopped after 12s · 2 steps" })).toBeInTheDocument();
    expect(screen.queryByText("Done")).toBeNull();
    // The line says it, so the footer does not say it again.
    expect(screen.queryByText("stopped")).toBeNull();
  });

  it("keeps the footer's mark for a turn cut off with nothing to fold", () => {
    item({ parts: [text("ans", "Half an ans")], wasStopped: true });

    expect(screen.getByText("stopped")).toBeInTheDocument();
  });
});

it("keeps a settled message out of a sibling's streaming rerender", async () => {
  const reduced = vi.spyOn(motion, "prefersReducedMotion").mockReturnValue(true);
  const settled = message({ id: "settled" });
  const content = vi.fn(() => "A settled answer");
  Object.defineProperty(settled, "content", { get: content });
  const streaming = message({ id: "live", content: "Starting", isStreaming: true });
  const { rerender } = render(
    <>
      <MessageItem message={settled} />
      <MessageItem message={streaming} />
    </>,
  );
  expect(content).toHaveBeenCalled();
  content.mockClear();
  rerender(
    <>
      <MessageItem message={settled} />
      <MessageItem message={{ ...streaming, content: "The next delta" }} />
    </>,
  );
  expect(content).not.toHaveBeenCalled();
  expect(await screen.findByText("The next delta")).toBeInTheDocument();
  reduced.mockRestore();
});

describe("a routine created in the conversation", () => {
  const routineId = "00000000-0000-4000-8000-000000000001";
  const agentId = "00000000-0000-4000-8000-000000000002";
  const toolCall: ToolCall = {
    id: "routine-call",
    name: "agenticos_create_routine",
    args: {},
    status: "completed",
    result: JSON.stringify({ id: routineId, agent_id: agentId, trigger_type: "schedule" }),
  };

  it("shows a management card to a signed-in person after the response finishes", () => {
    useAuthStore.setState({
      user: {
        id: "u-1",
        email: "ada@example.com",
        is_active: true,
        created_at: "2026-11-02T00:00:00Z",
      },
    });
    render(<MessageItem message={message({ toolCalls: [toolCall] })} />);
    expect(screen.getByTestId("routine-result")).toHaveTextContent(routineId);
  });

  it("does not fetch or expose routine controls on a public conversation", () => {
    render(<MessageItem message={message({ toolCalls: [toolCall] })} />);
    expect(screen.queryByTestId("routine-result")).not.toBeInTheDocument();
  });
});

describe("phone message actions", () => {
  it.each(["user", "assistant"] as const)(
    "offers an explicit toggle for a %s message",
    async (role) => {
      const regenerate = vi.fn();
      item({ role }, { onRegenerate: regenerate });
      const toggle = screen.getByRole("button", { name: "More" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      const controls = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
      expect(controls).toContainElement(screen.getByRole("button", { name: "Copy to clipboard" }));
      await userEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");
      if (role === "assistant") {
        await userEvent.click(screen.getByRole("button", { name: "Regenerate response" }));
        expect(regenerate).toHaveBeenCalledOnce();
      }
      await userEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    },
  );

  it("keeps stopped and interrupted voice status outside the folded actions", () => {
    item({ wasStopped: true, turnId: "call:1:assistant", interrupted: true });
    const toggle = screen.getByRole("button", { name: "More" });
    const controls = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(controls).not.toContainElement(screen.getByText("stopped"));
    expect(controls).not.toContainElement(screen.getByText("Voice"));
    expect(controls).not.toContainElement(screen.getByText("Interrupted"));
  });

  it("keeps actions reachable on the final segment without repeating its speaker", async () => {
    item({}, { continuesTurn: true, endsTurn: true });
    const toggle = screen.getByRole("button", { name: "More" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("Agent")).toBeNull();
  });

  it("does not offer a toggle before the streamed turn finishes", () => {
    item({ isStreaming: true });
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
  });
});

vi.mock("@/components/watches/watches-card", () => ({
  WatchesCard: ({ watchId }: { watchId: string }) => <div>Manage watch {watchId}</div>,
}));
it("keeps a successful watch write visible as an authorized management reference", () => {
  useAuthStore.setState({
    user: {
      id: "user",
      email: "user@example.com",
      is_active: true,
      created_at: "2026-11-01T00:00:00Z",
    },
  });
  const id = "11111111-1111-4111-8111-111111111111";
  item({
    toolCalls: [
      {
        id: "watch",
        name: "agenticos_create_watch",
        args: {},
        status: "completed",
        result: JSON.stringify({ id, connection_id: "22222222-2222-4222-8222-222222222222" }),
      },
    ],
  });
  expect(screen.getByText(`Manage watch ${id}`)).toBeInTheDocument();
});
