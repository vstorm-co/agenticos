import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentSelectionStore, useChatStore, useConversationStore } from "@/stores";
import { ChatScope } from "@/stores/chat-scope";
import type { Agent } from "@/types/agents";
import type { AssistantState } from "@/types/assistant";

import { AssistantWindow } from "./assistant-window";

const state = vi.hoisted(() => ({
  agents: [] as Agent[],
  search: "",
  startNewChat: vi.fn(),
  conversationsFor: vi.fn(),
  workflowsEnabled: vi.fn(),
  registryLoading: false,
  registryFetching: false,
  registryError: null as Error | null,
  refetchAgents: vi.fn(),
}));

vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: state.agents,
    isLoading: state.registryLoading,
    isFetching: state.registryFetching,
    error: state.registryError,
    refetch: state.refetchAgents,
  }),
}));
vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: state.agents,
    isLoading: state.registryLoading,
    isFetching: state.registryFetching,
    error: state.registryError,
    refetch: state.refetchAgents,
  }),
  usePermissions: () => ({ can: () => true }),
  useWorkflows: ({ enabled }: { enabled: boolean }) => {
    state.workflowsEnabled(enabled);
    return { workflows: [] };
  },
}));
vi.mock("@/hooks/use-conversations", () => ({
  useConversations: ({ agentId }: { agentId: string | null }) => {
    state.conversationsFor(agentId);
    return { startNewChat: async () => state.startNewChat(agentId) };
  },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ agentId }: { agentId: string }) => (
    <span data-testid="agent-avatar" data-agent-id={agentId} />
  ),
}));
vi.mock("@/components/chat/chat-container", () => ({
  ChatContainer: ({
    agentFixed,
    sendDisabled,
    emptyState,
  }: {
    agentFixed?: boolean;
    sendDisabled?: boolean;
    emptyState?: (onPick: (text: string) => void) => ReactNode;
  }) => (
    <div data-testid="chat" data-agent-fixed={agentFixed} data-send-disabled={sendDisabled}>
      {emptyState ? emptyState(() => undefined) : <div data-testid="agent-welcome" />}
    </div>
  ),
}));
vi.mock("./assistant-history", () => ({
  AssistantHistory: ({
    agentId,
    onClose,
    onNew,
  }: {
    agentId: string;
    onClose: () => void;
    onNew: () => void;
  }) => (
    <div data-testid="history" data-agent-id={agentId}>
      <button type="button" onClick={onClose}>
        Close history
      </button>
      <button type="button" onClick={onNew}>
        Start from history
      </button>
    </div>
  ),
}));

const agent = (id: string, name: string, extra: Partial<Agent> = {}): Agent => ({
  id,
  name,
  slug: id,
  description: null,
  status: "published",
  visibility: "org",
  owner_user_id: null,
  current_version_id: "v1",
  can_run: true,
  ...extra,
});

const MAIN: AssistantState = {
  status: "ready",
  agent_id: "a1",
  slug: "ai-architect",
  name: "Internal assistant name",
  named_by_default: true,
  greeting: "Main agent greeting",
  avatar_url: null,
  wears_mark: true,
  avatar_color: null,
  can_use: true,
  can_configure: false,
};

const windowProps: ComponentProps<typeof AssistantWindow> = {
  assistant: MAIN,
  agentId: "a1",
  open: true,
  prompt: null,
  page: { path: "/agents", title: "Agents", captured_at: "2026-01-01T00:00:00.000Z" },
  getPageContext: () => ({
    path: "/agents",
    title: "Agents",
    captured_at: "2026-01-01T00:00:00.000Z",
  }),
  tipsOff: false,
  onTipsOff: vi.fn(),
  onOpenChange: vi.fn(),
  onConsoleLink: vi.fn(),
};

interface ScopeApis {
  selection: ReturnType<typeof useAgentSelectionStore.useApi>;
  chat: ReturnType<typeof useChatStore.useApi>;
  conversation: ReturnType<typeof useConversationStore.useApi>;
}

let scope: ScopeApis | null = null;

function ScopeProbe() {
  scope = {
    selection: useAgentSelectionStore.useApi(),
    chat: useChatStore.useApi(),
    conversation: useConversationStore.useApi(),
  };
  return null;
}

function windowTree(
  initial: string | null = "a1",
  props: Partial<ComponentProps<typeof AssistantWindow>> = {},
) {
  return (
    <ChatScope agentId={initial}>
      <ScopeProbe />
      <AssistantWindow {...windowProps} {...props} />
    </ChatScope>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  scope = null;
  state.search = "";
  state.registryLoading = false;
  state.registryFetching = false;
  state.registryError = null;
  state.refetchAgents.mockResolvedValue(undefined);
  state.agents = [agent("a1", "Internal assistant name"), agent("a2", "Scheduler")];
  useAgentSelectionStore.setState({
    selectedAgentId: "main-chat-agent",
    defaultAgentId: "main-chat-default",
    selectedWorkflowId: null,
  });
});

afterEach(() => {
  useAgentSelectionStore.setState({
    selectedAgentId: null,
    defaultAgentId: null,
    selectedWorkflowId: null,
  });
  useChatStore.setState({ messages: [] });
  useConversationStore.getState().reset();
});

describe("choosing who answers in the floating assistant", () => {
  it("starts with the main assistant's localized name, face and greeting", () => {
    render(windowTree());

    const picker = screen.getByRole("button", { name: "Agent: Architect" });
    expect(within(picker).getByTestId("agent-avatar")).toHaveAttribute("data-agent-id", "a1");
    expect(screen.getByRole("dialog", { name: "Architect" })).toBeInTheDocument();
    expect(screen.getByText("Main agent greeting")).toBeInTheDocument();
    expect(screen.getByTestId("chat")).toHaveAttribute("data-agent-fixed", "true");
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "false");
  });

  it("keeps an administrator's chosen main-assistant name", () => {
    render(windowTree("a1", { assistant: { ...MAIN, name: "Guide", named_by_default: false } }));

    expect(screen.getByRole("button", { name: "Agent: Guide" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Guide" })).toBeInTheDocument();
  });

  it("switches the scoped answerer while retaining the thread and leaving the main chat alone", async () => {
    render(windowTree());
    const originalChat = scope!.chat;
    act(() => {
      scope!.conversation.getState().setCurrentConversationId("floating-thread");
      scope!.chat.getState().addMessage({
        id: "message-1",
        role: "user",
        content: "Explain this page.",
        timestamp: new Date(),
      });
    });

    await userEvent.click(screen.getByRole("button", { name: "Agent: Architect" }));
    await userEvent.click(screen.getByRole("radio", { name: /Scheduler/ }));
    await userEvent.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: "Agent: Scheduler" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Scheduler" })).toBeInTheDocument();
    expect(screen.queryByText("Main agent greeting")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-welcome")).toBeInTheDocument();
    expect(scope!.selection.getState().selectedAgentId).toBe("a2");
    expect(scope!.chat).toBe(originalChat);
    expect(scope!.chat.getState().messages[0]?.id).toBe("message-1");
    expect(scope!.conversation.getState().currentConversationId).toBe("floating-thread");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("main-chat-agent");
    expect(useAgentSelectionStore.getState().defaultAgentId).toBe("main-chat-default");
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("uses the selected agent for history and both new-conversation controls", async () => {
    render(windowTree());
    act(() => scope!.selection.getState().select("a2"));

    await userEvent.click(screen.getByRole("button", { name: "Conversations" }));
    expect(screen.getByTestId("history")).toHaveAttribute("data-agent-id", "a2");
    expect(state.conversationsFor).toHaveBeenLastCalledWith("a2");

    await userEvent.click(screen.getByRole("button", { name: "Start from history" }));
    expect(screen.queryByTestId("history")).not.toBeInTheDocument();
    expect(state.startNewChat).toHaveBeenLastCalledWith("a2");

    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(state.startNewChat).toHaveBeenCalledTimes(2);
    expect(state.startNewChat).toHaveBeenLastCalledWith("a2");
  });

  it("ignores host-page routing and offers no workflow or standing-default controls", async () => {
    state.search = "agent=a2";
    render(windowTree());
    act(() => scope!.selection.getState().setDefault("a2"));

    await userEvent.click(screen.getByRole("button", { name: "Agent: Architect" }));

    expect(scope!.selection.getState().selectedAgentId).toBe("a1");
    expect(state.workflowsEnabled).toHaveBeenLastCalledWith(false);
    expect(screen.queryByRole("radiogroup", { name: "Workflows" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /default agent/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
  });

  it.each([
    agent("unavailable", "View only", { can_run: false }),
    agent("unavailable", "Draft", { status: "draft", current_version_id: null }),
    agent("unavailable", "Archived", { status: "archived" }),
  ])("disables sending without substituting for $name", async (unavailable) => {
    state.agents = [...state.agents, unavailable];
    render(windowTree("unavailable"));

    expect(scope!.selection.getState().selectedAgentId).toBe("unavailable");
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");

    await userEvent.click(screen.getByRole("button", { name: "Agent: none selected" }));
    expect(screen.queryByRole("radio", { name: unavailable.name })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Scheduler/ }));

    expect(scope!.selection.getState().selectedAgentId).toBe("a2");
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "false");
  });

  it("holds an unresolved selection and an empty selection for an explicit choice", () => {
    const { unmount } = render(windowTree("not-listed"));
    expect(scope!.selection.getState().selectedAgentId).toBe("not-listed");
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");
    unmount();

    render(windowTree(null));
    expect(scope!.selection.getState().selectedAgentId).toBeNull();
    expect(screen.getByRole("button", { name: "Conversations" })).toBeDisabled();
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");
  });
});

it.each(["missing", "draft"] as const)(
  "refreshes a ready assistant's %s registry entry once after the list settles",
  (cached) => {
    const main = agent("a1", "Internal assistant name");
    const specialist = agent("a2", "Scheduler");
    state.agents =
      cached === "missing"
        ? [specialist]
        : [specialist, { ...main, status: "draft", current_version_id: null }];
    state.registryLoading = true;
    const { rerender } = render(windowTree());
    expect(state.refetchAgents).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");

    state.registryLoading = false;
    state.registryFetching = true;
    rerender(windowTree());
    expect(state.refetchAgents).not.toHaveBeenCalled();

    state.registryFetching = false;
    rerender(windowTree());
    expect(state.refetchAgents).toHaveBeenCalledTimes(1);
    expect(scope!.selection.getState().selectedAgentId).toBe("a1");
    rerender(windowTree());
    expect(state.refetchAgents).toHaveBeenCalledTimes(1);

    state.agents = [main, specialist];
    rerender(windowTree());
    expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "false");
    expect(screen.getByRole("button", { name: "Agent: Architect" })).toBeInTheDocument();
    expect(state.refetchAgents).toHaveBeenCalledTimes(1);
  },
);

it("preserves explicit main-agent run denial", () => {
  state.agents = [agent("a1", "Internal assistant name", { can_run: false })];
  render(windowTree());
  expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");
  expect(scope!.selection.getState().selectedAgentId).toBe("a1");
  expect(state.refetchAgents).not.toHaveBeenCalled();
});

it("waits until the panel opens before refreshing an absent main agent", () => {
  state.agents = [agent("a2", "Scheduler")];
  const { rerender } = render(windowTree("a1", { open: false }));
  expect(state.refetchAgents).not.toHaveBeenCalled();
  rerender(windowTree());
  expect(state.refetchAgents).toHaveBeenCalledTimes(1);
});

it("does not repeatedly refresh a failed registry query", () => {
  state.agents = [];
  state.registryError = new Error("Registry unavailable");
  render(windowTree());
  expect(screen.getByTestId("chat")).toHaveAttribute("data-send-disabled", "true");
  expect(state.refetchAgents).not.toHaveBeenCalled();
});
