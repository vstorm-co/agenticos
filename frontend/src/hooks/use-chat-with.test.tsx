import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { useAgentSelectionStore, useConversationStore, useChatStore } from "@/stores";
import { useChatWith } from "./use-chat-with";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.value }));

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(async () => ({ items: [], total: 0 })) },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  useAgentSelectionStore.setState({ selectedAgentId: "a-old", defaultAgentId: null });
  useChatStore.setState({
    messages: [{ id: "m-old", role: "user", content: "old question", timestamp: new Date() }],
  });
  useConversationStore.getState().setCurrentConversationId("c-old");
});

describe("useChatWith", () => {
  it("starts a new chat with the agent the address names, and takes the name off it", () => {
    window.history.replaceState({}, "", "/chat?with=a-1&view=archived");
    params.value = new URLSearchParams("with=a-1&view=archived");

    renderHook(() => useChatWith(), { wrapper });

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-1");
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(window.location.search).toBe("?view=archived");
  });

  it("leaves the chat alone without one", () => {
    params.value = new URLSearchParams("id=c-old");

    renderHook(() => useChatWith(), { wrapper });

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-old");
    expect(useConversationStore.getState().currentConversationId).toBe("c-old");
  });
  it("starts a blank chat through the normal action and consumes the desktop request", () => {
    window.history.replaceState({}, "", "/chat?new=first");
    params.value = new URLSearchParams("new=first");
    useAgentSelectionStore.setState({ defaultAgentId: "a-default" });
    useConversationStore.getState().setPendingProjectId("previous-project");

    renderHook(() => useChatWith(), { wrapper });

    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useConversationStore.getState().pendingProjectId).toBeNull();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-default");
    expect(window.location.search).toBe("");
  });

  it("honors another click while chat is mounted, without consuming the same request twice", () => {
    window.history.replaceState({}, "", "/chat?new=first");
    params.value = new URLSearchParams("new=first");
    const { rerender } = renderHook(() => useChatWith(), { wrapper });
    act(() => {
      useConversationStore.getState().setCurrentConversationId("second-chat");
      useChatStore.setState({
        messages: [
          { id: "m-second", role: "user", content: "second question", timestamp: new Date() },
        ],
      });
    });
    rerender();
    expect(useChatStore.getState().messages).toHaveLength(1);

    window.history.replaceState({}, "", "/chat?new=second");
    params.value = new URLSearchParams("new=second");
    rerender();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useChatStore.getState().messages).toEqual([]);
  });
});

it("accepts the same desktop request again after leaving the request route", () => {
  params.value = new URLSearchParams("new=again");
  const { rerender } = renderHook(() => useChatWith(), { wrapper });
  expect(useConversationStore.getState().currentConversationId).toBeNull();
  params.value = new URLSearchParams();
  rerender();
  act(() => useConversationStore.getState().setCurrentConversationId("opened-later"));
  params.value = new URLSearchParams("new=again");
  rerender();
  expect(useConversationStore.getState().currentConversationId).toBeNull();
});

it("does not consume an unchanged request again when another query field changes", () => {
  params.value = new URLSearchParams("new=once&with=a-1");
  const { rerender } = renderHook(() => useChatWith(), { wrapper });
  expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-1");
  act(() => useConversationStore.getState().setCurrentConversationId("keep-open"));
  params.value = new URLSearchParams("new=once&with=a-2");
  rerender();
  expect(useConversationStore.getState().currentConversationId).toBe("keep-open");
  expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-1");
});
