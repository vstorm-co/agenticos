import userEvent from "@testing-library/user-event";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationForkRead } from "@/lib/conversation-forks-api";
import { useAuthStore } from "@/stores/auth-store";
import { PersonalSideThreadPanel } from "./personal-side-thread-panel";

const state = vi.hoisted(() => ({
  tenant: "org-a" as string | null,
  mounts: 0,
  selectConversation: vi.fn(),
}));

vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => state.tenant }));
vi.mock("@/hooks/use-conversations", () => ({
  useConversations: () => ({ selectConversation: state.selectConversation }),
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("./chat-container", async () => {
  const React = await import("react");
  const stores = await import("@/stores");
  return {
    ChatContainer: (props: {
      requestedConversationId?: string;
      requestedMessageId?: string | null;
      requestedThreadRootId?: string | null;
      messageJumpRevision?: number;
      onOpenParent?: (target: { conversationId: string; messageId: string | null }) => void;
      onOpenMessage?: (target: {
        conversationId: string;
        messageId: string;
        threadRootMessageId?: string | null;
      }) => void;
      onOpenThread?: (rootId: string) => void;
      onCloseThread?: () => void;
    }) => {
      const [instance] = React.useState(() => ++state.mounts);
      const setCurrentConversationId = stores.useConversationStore(
        (store) => store.setCurrentConversationId,
      );
      return React.createElement(
        "div",
        {
          "data-testid": "child-chat",
          "data-instance": String(instance),
          "data-conversation": props.requestedConversationId,
          "data-message": props.requestedMessageId ?? "",
          "data-thread-root": props.requestedThreadRootId ?? "",
          "data-jump-revision": String(props.messageJumpRevision),
        },
        React.createElement(
          "button",
          {
            type: "button",
            onClick: () =>
              props.onOpenParent?.({
                conversationId: "parent-from-child",
                messageId: "parent-answer",
              }),
          },
          "Child parent link",
        ),
        React.createElement(
          "button",
          {
            type: "button",
            onClick: () =>
              props.onOpenMessage?.({
                conversationId: props.requestedConversationId ?? "",
                messageId: "local-message",
              }),
          },
          "Open local result",
        ),
        React.createElement(
          "button",
          {
            type: "button",
            onClick: () =>
              props.onOpenMessage?.({ conversationId: "another-chat", messageId: "bad" }),
          },
          "Open unrelated result",
        ),
        React.createElement(
          "button",
          { type: "button", onClick: () => props.onOpenThread?.("local-thread") },
          "Open local thread",
        ),
        React.createElement(
          "button",
          { type: "button", onClick: () => props.onCloseThread?.() },
          "Close local thread",
        ),
        React.createElement(
          "button",
          {
            type: "button",
            onClick: () => setCurrentConversationId(props.requestedConversationId ?? null),
          },
          "Mark child selected",
        ),
      );
    },
  };
});

const user = {
  id: "user-a",
  email: "person@example.test",
  is_active: true,
  created_at: "2026-11-16T10:00:00Z",
};

const fork: ConversationForkRead = {
  id: "child-a",
  title: "Alternative path",
  created_at: "2026-11-17T12:00:00Z",
  updated_at: null,
  is_archived: false,
  forked_from: {
    conversation_id: "source-a",
    message_id: "answer-a",
    title: "Main conversation",
  },
};

beforeEach(() => {
  state.tenant = "org-a";
  state.mounts = 0;
  state.selectConversation.mockReset();
  useAuthStore.setState({ user });
});

describe("PersonalSideThreadPanel", () => {
  it("opens the child in a fresh isolated scope when the account or organization changes", async () => {
    const onOpenParent = vi.fn();
    const { rerender } = render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={onOpenParent}
      />,
    );

    const firstInstance = await screen.findByTestId("child-chat");
    expect(firstInstance).toHaveAttribute("data-conversation", "child-a");
    const initialInstanceId = firstInstance.getAttribute("data-instance");
    expect(state.selectConversation).toHaveBeenCalledExactlyOnceWith("child-a");

    state.tenant = "org-b";
    rerender(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={onOpenParent}
      />,
    );

    const scopedInstance = await screen.findByTestId("child-chat");
    expect(scopedInstance.getAttribute("data-instance")).not.toBe(initialInstanceId);
    expect(state.selectConversation).toHaveBeenCalledTimes(2);

    act(() => useAuthStore.setState({ user: { ...user, id: "user-b" } }));
    rerender(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={onOpenParent}
      />,
    );
    expect((await screen.findByTestId("child-chat")).getAttribute("data-instance")).not.toBe(
      scopedInstance.getAttribute("data-instance"),
    );
  });

  it("rejects a child whose parent does not match the selected conversation", () => {
    render(
      <PersonalSideThreadPanel
        sourceConversationId="another-source"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("error");
    expect(screen.queryByTestId("child-chat")).not.toBeInTheDocument();
  });

  it("uses the untitled label when the child has no title", () => {
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={{ ...fork, title: null }}
        onClose={vi.fn()}
        onOpenParent={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "untitledFork" })).toBeInTheDocument();
  });

  it("does not mount a child before tenant and account identity are ready", () => {
    state.tenant = null;
    useAuthStore.setState({ user: null });
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("error");
    expect(screen.queryByTestId("child-chat")).not.toBeInTheDocument();
  });

  it("does not mount a child when the account is signed out of a ready tenant", () => {
    useAuthStore.setState({ user: null });
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("error");
    expect(screen.queryByTestId("child-chat")).not.toBeInTheDocument();
  });

  it("returns focus to the opener when the panel is closed normally", async () => {
    const onClose = vi.fn();
    render(
      <button type="button" id="side-thread-opener">
        Open side thread
      </button>,
    );
    document.getElementById("side-thread-opener")?.focus();
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={onClose}
        onOpenParent={vi.fn()}
      />,
    );

    await screen.findByTestId("child-chat");
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledExactlyOnceWith());
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("side-thread-opener")),
    );
    expect(screen.queryByRole("dialog", { name: "Alternative path" })).not.toBeInTheDocument();
  });

  it("closes on Escape and reports the normal close", async () => {
    const onClose = vi.fn();
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={onClose}
        onOpenParent={vi.fn()}
      />,
    );

    await screen.findByTestId("child-chat");
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(onClose).toHaveBeenCalledExactlyOnceWith());
    expect(screen.queryByRole("dialog", { name: "Alternative path" })).not.toBeInTheDocument();
  });

  it("opens the parent answer after suppressing focus restoration to the old opener", async () => {
    const onOpenParent = vi.fn(() => document.getElementById("parent-answer")?.focus());
    render(
      <>
        <button type="button" id="side-thread-opener">
          Open side thread
        </button>
        <button type="button" id="parent-answer" tabIndex={-1}>
          Parent answer
        </button>
      </>,
    );
    document.getElementById("side-thread-opener")?.focus();
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={onOpenParent}
      />,
    );

    await screen.findByTestId("child-chat");
    await userEvent.click(screen.getByRole("button", { name: "backToParent" }));

    await waitFor(() =>
      expect(onOpenParent).toHaveBeenCalledExactlyOnceWith({
        conversationId: "source-a",
        messageId: "answer-a",
      }),
    );
    expect(document.activeElement).toBe(document.getElementById("parent-answer"));
  });

  it("keeps local message and thread jumps in the child scope", async () => {
    render(
      <PersonalSideThreadPanel
        sourceConversationId="source-a"
        fork={fork}
        onClose={vi.fn()}
        onOpenParent={vi.fn()}
      />,
    );
    let child = await screen.findByTestId("child-chat");

    await userEvent.click(screen.getByRole("button", { name: "Open unrelated result" }));
    expect(child).toHaveAttribute("data-message", "");
    expect(child).toHaveAttribute("data-jump-revision", "0");

    await userEvent.click(screen.getByRole("button", { name: "Open local result" }));
    child = screen.getByTestId("child-chat");
    expect(child).toHaveAttribute("data-message", "local-message");
    expect(child).toHaveAttribute("data-jump-revision", "1");

    await userEvent.click(screen.getByRole("button", { name: "Open local thread" }));
    child = screen.getByTestId("child-chat");
    expect(child).toHaveAttribute("data-message", "local-thread");
    expect(child).toHaveAttribute("data-thread-root", "local-thread");
    expect(child).toHaveAttribute("data-jump-revision", "2");

    await userEvent.click(screen.getByRole("button", { name: "Close local thread" }));
    child = screen.getByTestId("child-chat");
    expect(child).toHaveAttribute("data-message", "");
    expect(child).toHaveAttribute("data-thread-root", "");
    expect(child).toHaveAttribute("data-jump-revision", "2");

    await userEvent.click(screen.getByRole("button", { name: "Mark child selected" }));
    expect(state.selectConversation).toHaveBeenCalledExactlyOnceWith("child-a");
  });
});
