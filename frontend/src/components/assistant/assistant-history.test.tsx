import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import type { Conversation } from "@/types";
import { AssistantHistory } from "./assistant-history";

/**
 * The Architect's earlier conversations, drawn as the chat page's list draws
 * them: the face, who and when over the title, the unread dot, the day headings.
 */

const state = vi.hoisted(() => ({
  conversations: [] as Conversation[],
  currentConversationId: null as string | null,
  selectConversation: vi.fn(),
}));

vi.mock("@/hooks/use-conversations", () => ({
  useConversations: () => ({
    conversations: state.conversations,
    currentConversationId: state.currentConversationId,
    fetchConversations: vi.fn(),
    selectConversation: state.selectConversation,
  }),
}));

const ARCHITECT = { id: "a1", slug: "architect", name: "Architect", has_avatar: false };
const BROWSER = { id: "a2", slug: "browser-check", name: "Browser check", has_avatar: false };

function conversation(id: string, overrides: Partial<Conversation> = {}): Conversation {
  const now = new Date().toISOString();
  return {
    id,
    title: `Thread ${id}`,
    created_at: now,
    updated_at: now,
    agents: [ARCHITECT],
    ...overrides,
  } as Conversation;
}

function mount(onClose = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <AssistantHistory agentId="a1" onClose={onClose} onNew={vi.fn()} />
    </NextIntlClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  state.conversations = [];
  state.currentConversationId = null;
  state.selectConversation.mockReset();
});

describe("the Architect's conversation list", () => {
  it("heads the threads by day and names who answered and when over each title", () => {
    state.conversations = [conversation("1")];
    mount();

    expect(screen.getByRole("heading", { name: "Today" })).toBeVisible();
    const row = screen.getByRole("button", { name: /Thread 1/ });
    expect(within(row).getByText(/^Architect · /)).toBeVisible();
  });

  it("counts the agents of a thread several answered in, as the chat list does", () => {
    state.conversations = [conversation("1", { agents: [ARCHITECT, BROWSER] })];
    mount();

    expect(screen.getByText(/^2 agents · /)).toBeVisible();
  });

  it("says only when for a thread no agent answered, with the plain mark", () => {
    state.conversations = [conversation("1", { agents: [], title: undefined })];
    mount();

    expect(screen.getByText(messages.assistantWidget.untitled)).toBeVisible();
    expect(screen.queryByText(/ · /)).toBeNull();
  });

  it("marks an answer not yet read, but not on the thread that is open", () => {
    state.conversations = [
      conversation("1", { unread: true }),
      conversation("2", { unread: true }),
    ];
    state.currentConversationId = "2";
    mount();

    const unread = screen.getAllByRole("status", { name: messages.chat.sidebar.unread });
    expect(unread).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Thread 2/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("opens a thread and closes the list", () => {
    state.conversations = [conversation("1")];
    const onClose = mount();

    fireEvent.click(screen.getByRole("button", { name: /Thread 1/ }));

    expect(state.selectConversation).toHaveBeenCalledWith("1");
    expect(onClose).toHaveBeenCalled();
  });
});
