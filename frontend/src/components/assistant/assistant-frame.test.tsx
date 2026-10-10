import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatPrompt } from "@/components/chat/chat-container";
import { ASK, CONTEXT, HISTORY, NEW } from "@/lib/assistant-messages";
import type { AssistantState } from "@/types/assistant";

import { AssistantFrame } from "./assistant-frame";

const state = vi.hoisted(() => ({
  assistant: null as Partial<AssistantState> | null,
  select: vi.fn(),
  startNewChat: vi.fn(),
  fetchConversations: vi.fn(),
  selectConversation: vi.fn(),
  conversations: [] as { id: string; title: string | null }[],
  person: null as string | null,
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({ assistant: state.assistant, isLoading: false }),
}));
vi.mock("@/hooks/use-conversations", () => ({
  useConversations: () => ({
    startNewChat: state.startNewChat,
    fetchConversations: state.fetchConversations,
    selectConversation: state.selectConversation,
    conversations: state.conversations,
  }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (pick: (s: { select: typeof state.select }) => unknown) =>
    pick({ select: state.select }),
  useAuthStore: (pick: (s: { user: { full_name: string | null } | null }) => unknown) =>
    pick({ user: state.person === null ? null : { full_name: state.person } }),
}));
// The chat is tested on its own; here it shows what it was asked and its empty state.
vi.mock("@/components/chat/chat-container", () => ({
  ChatContainer: ({
    prompt,
    emptyState,
  }: {
    prompt: ChatPrompt | null;
    emptyState: (onPick: (text: string) => void) => React.ReactNode;
  }) => (
    <div>
      <output>{prompt ? `${prompt.id}:${prompt.text}` : "no prompt"}</output>
      {emptyState((text) => state.selectConversation(`picked:${text}`))}
    </div>
  ),
}));

/** A message from the console, as the frame receives it. */
function send(data: unknown, origin = window.location.origin) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, origin }));
  });
}

beforeEach(() => {
  state.assistant = { name: "AI Architect", greeting: null };
  state.conversations = [];
  state.person = null;
  for (const fn of [
    state.select,
    state.startNewChat,
    state.fetchConversations,
    state.selectConversation,
  ]) {
    fn.mockReset();
  }
});

describe("the assistant's frame", () => {
  it("talks to the assistant it was opened for", () => {
    render(<AssistantFrame agentId="a1" />);

    expect(state.select).toHaveBeenCalledWith("a1");
  });

  it("asks what the console sends, each prompt a new one", () => {
    render(<AssistantFrame agentId="a1" />);

    send({ type: ASK, text: "Build me an agent" });
    expect(screen.getByRole("status")).toHaveTextContent("1:Build me an agent");
    send({ type: ASK, text: "Build me an agent" });
    expect(screen.getByRole("status")).toHaveTextContent("2:Build me an agent");
  });

  it("ignores a message from anywhere else", () => {
    render(<AssistantFrame agentId="a1" />);

    send({ type: ASK, text: "Delete everything" }, "https://evil.example");

    expect(screen.getByRole("status")).toHaveTextContent("no prompt");
  });

  it("asks about the page the reader is on", () => {
    render(<AssistantFrame agentId="a1" />);

    send({ type: CONTEXT, path: "/runs", title: "Runs" });
    fireEvent.click(screen.getByRole("button", { name: "What am I looking at?" }));

    expect(state.selectConversation).toHaveBeenCalledWith(
      expect.stringMatching(/^picked:I'm on the page "Runs" \(\/runs\)/),
    );
  });

  it("starts a new conversation", () => {
    render(<AssistantFrame agentId="a1" />);

    send({ type: NEW });

    expect(state.startNewChat).toHaveBeenCalled();
  });

  it("toggles the history, which opens a conversation and closes itself", () => {
    state.conversations = [
      { id: "c1", title: "Budget question" },
      { id: "c2", title: null },
    ];
    render(<AssistantFrame agentId="a1" />);

    send({ type: HISTORY });
    expect(state.fetchConversations).toHaveBeenCalled();
    expect(screen.getByText("Untitled conversation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Budget question" }));

    expect(state.selectConversation).toHaveBeenCalledWith("c1");
    expect(screen.queryByText("Untitled conversation")).toBeNull();
  });

  it("closes the history from its own button, from the toggle, and on a new conversation", () => {
    render(<AssistantFrame agentId="a1" />);

    send({ type: HISTORY });
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to the conversation" }));
    expect(screen.queryByText("No conversations yet.")).toBeNull();

    send({ type: HISTORY });
    send({ type: HISTORY });
    expect(screen.queryByText("No conversations yet.")).toBeNull();

    send({ type: HISTORY });
    send({ type: NEW });
    expect(screen.queryByText("No conversations yet.")).toBeNull();
  });
});

describe("the assistant's welcome", () => {
  it("greets the reader by first name, or without one", () => {
    state.person = "Kacper Włodarczyk";
    const { unmount } = render(<AssistantFrame agentId="a1" />);
    expect(screen.getByText("Hi Kacper, I'm AI Architect. What shall we do?")).toBeInTheDocument();
    unmount();

    state.person = null;
    render(<AssistantFrame agentId="a1" />);
    expect(screen.getByText("Hi, I'm AI Architect. What shall we do?")).toBeInTheDocument();
  });

  it("says the organization's own greeting when it has one", () => {
    state.assistant = { name: "Ola", greeting: "Cześć! W czym pomóc?" };
    render(<AssistantFrame agentId="a1" />);

    expect(screen.getByText("Cześć! W czym pomóc?")).toBeInTheDocument();
  });

  it("turns a tile into the first message", () => {
    render(<AssistantFrame agentId="a1" />);

    fireEvent.click(screen.getByRole("button", { name: "What am I looking at?" }));
    fireEvent.click(screen.getByRole("button", { name: "Ready-made recipes" }));

    expect(state.selectConversation).toHaveBeenCalledWith(
      "picked:Explain what this platform can do for me, in plain language.",
    );
    expect(state.selectConversation).toHaveBeenCalledWith(
      expect.stringMatching(/^picked:Show me the ready-made recipes/),
    );
  });

  it("greets nobody until it knows who it is", () => {
    state.assistant = null;
    render(<AssistantFrame agentId="a1" />);

    expect(screen.queryByText(/What shall we do/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Ready-made recipes" })).toBeNull();
  });
});
