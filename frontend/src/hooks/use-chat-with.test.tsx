import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useChatWith } from "./use-chat-with";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.value }));

beforeEach(() => {
  useAgentSelectionStore.setState({ selectedAgentId: "a-old" });
  useConversationStore.getState().setCurrentConversationId("c-old");
});

describe("useChatWith", () => {
  it("starts a new chat with the agent the address names, and takes the name off it", () => {
    window.history.replaceState({}, "", "/chat?with=a-1&view=archived");
    params.value = new URLSearchParams("with=a-1&view=archived");

    renderHook(() => useChatWith());

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-1");
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(window.location.search).toBe("?view=archived");
  });

  it("leaves the chat alone without one", () => {
    params.value = new URLSearchParams("id=c-old");

    renderHook(() => useChatWith());

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-old");
    expect(useConversationStore.getState().currentConversationId).toBe("c-old");
  });
});
