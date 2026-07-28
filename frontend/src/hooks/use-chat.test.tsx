import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChat } from "./use-chat";
import { useAgentSelectionStore, useChatStore, useKBSelectionStore } from "@/stores";

// The socket itself is not under test: what matters is the frame the hook hands
// it, because that frame is the whole contract with the backend. The mock also
// keeps hold of the inbound handler so a server event can be replayed.
const { sent, socket } = vi.hoisted(() => ({
  sent: vi.fn(),
  socket: { onMessage: null as ((event: MessageEvent) => void) | null },
}));

vi.mock("./use-websocket", () => ({
  useWebSocket: (options: { onMessage?: (event: MessageEvent) => void }) => {
    socket.onMessage = options.onMessage ?? null;
    return {
      isConnected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      sendMessage: sent,
    };
  },
}));

/** The single frame `sendMessage` produced. */
function lastFrame(): Record<string, unknown> {
  expect(sent).toHaveBeenCalledTimes(1);
  return sent.mock.calls[0]![0] as Record<string, unknown>;
}

/** Replay one server event onto the hook, the way the socket would. */
function receive(type: string, data: Record<string, unknown>): void {
  act(() =>
    socket.onMessage?.(new MessageEvent("message", { data: JSON.stringify({ type, data }) })),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useKBSelectionStore.setState({ activeKBIds: [] });
  useChatStore.getState().clearMessages();
});

describe("useChat — which agent a turn is addressed to", () => {
  it("names the selected agent so the backend runs it", () => {
    useAgentSelectionStore.getState().select("agent-1");

    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame().agent_id).toBe("agent-1");
  });

  it("sends no agent_id for the general assistant", () => {
    // Not `agent_id: null`, not an empty string: the assistant is reached by the
    // frame that never mentions an agent, which is exactly what a client knowing
    // nothing about published agents sends.
    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame()).not.toHaveProperty("agent_id");
  });

  it("names whatever is selected when the frame leaves, not when the hook mounted", () => {
    // The pick happens after mount. A selection captured in the render closure
    // would keep addressing the assistant for the life of the page.
    const { result } = renderHook(() => useChat());
    act(() => useAgentSelectionStore.getState().select("agent-2"));
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame().agent_id).toBe("agent-2");
  });

  it("adds the agent to the frame without disturbing the rest of it", () => {
    // `agent_id` is one more field, not a different frame. The model override
    // now names a vault profile rather than a bare model name, and it applies
    // to a published agent as well as to the assistant — overriding an agent's
    // model used to be silently ignored.
    useAgentSelectionStore.getState().select("agent-1");
    useKBSelectionStore.getState().setActiveKBIds(["kb-1"]);

    const { result } = renderHook(() => useChat());
    act(() => {
      result.current.setModelProfile("profile-1");
      result.current.sendMessage("hello");
    });

    expect(lastFrame()).toMatchObject({
      message: "hello",
      agent_id: "agent-1",
      active_knowledge_base_ids: ["kb-1"],
      model_profile_id: "profile-1",
    });
  });
});

describe("useChat — attributing the answer", () => {
  it("credits the answer to the agent the turn was sent to", () => {
    useAgentSelectionStore.getState().select("agent-1");

    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hello"));
    // Switching while the answer streams must not re-credit a run that is
    // already under way to the newly picked agent.
    act(() => useAgentSelectionStore.getState().select("agent-2"));
    receive("model_request_start", {});

    const assistant = useChatStore.getState().messages.find((m) => m.role === "assistant");
    expect(assistant?.agentId).toBe("agent-1");
  });

  it("leaves an assistant turn unattributed", () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hello"));
    receive("model_request_start", {});

    const assistant = useChatStore.getState().messages.find((m) => m.role === "assistant");
    expect(assistant?.agentId).toBeUndefined();
  });
});
