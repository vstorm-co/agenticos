import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChat } from "./use-chat";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useOrgStore,
} from "@/stores";

// The socket itself is not under test: what matters is the frame the hook hands
// it, because that frame is the whole contract with the backend. The mock also
// keeps hold of the inbound handler so a server event can be replayed.
// A decision on a parked call goes to the same REST endpoints the approvals queue
// uses. It used to be a WebSocket `resume` frame the server silently discarded, so
// asserting on the frame is exactly what let that pass.
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { post } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { sent, socket, connect, disconnect } = vi.hoisted(() => ({
  sent: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
  socket: {
    onMessage: null as ((event: MessageEvent) => void) | null,
    onClose: null as (() => void) | null,
    url: "",
    protocols: undefined as string[] | undefined,
    isConnected: true,
  },
}));

/**
 * `useChat` resolves the tenant through the organizations query, so it needs a
 * client - it clears a queued message when the organization moves, and a
 * message queued in one organization must not be sent as another.
 */
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Seeded rather than fetched: these tests count requests, and an
  // organizations query going out for the tenant would be a request none of
  // them made.
  client.setQueryData(qk.organizations.list(), []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

vi.mock("./use-websocket", () => ({
  useWebSocket: (options: {
    url: string;
    protocols?: string[];
    onMessage?: (event: MessageEvent) => void;
    onClose?: () => void;
  }) => {
    socket.onMessage = options.onMessage ?? null;
    socket.onClose = options.onClose ?? null;
    socket.url = options.url;
    socket.protocols = options.protocols;
    return {
      isConnected: socket.isConnected,
      connect,
      disconnect,
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

/** The last frame `sendMessage` produced, whichever number it was. */
function frame(nth = 0): Record<string, unknown> {
  return sent.mock.calls[nth]![0] as Record<string, unknown>;
}

/** The assistant message being streamed. */
function streaming() {
  return useChatStore.getState().messages.find((message) => message.role === "assistant");
}

beforeEach(() => {
  vi.clearAllMocks();
  socket.isConnected = true;
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useAuthStore.setState({ accessToken: "t-1" });
  useOrgStore.setState({ activeOrgId: null });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  window.history.replaceState({}, "", "/chat");
});

describe("useChat - which agent a turn is addressed to", () => {
  it("names the selected agent so the backend runs it", () => {
    useAgentSelectionStore.getState().select("agent-1");

    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame().agent_id).toBe("agent-1");
  });

  it("omits agent_id entirely when nothing is selected", () => {
    // Not `agent_id: null`, not an empty string: the backend refuses a frame
    // that names no agent, and it should refuse an honest frame - one that
    // omits the field - rather than parse a placeholder.
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame()).not.toHaveProperty("agent_id");
  });

  it("names whatever is selected when the frame leaves, not when the hook mounted", () => {
    // The pick happens after mount. A selection captured in the render closure
    // would keep addressing the assistant for the life of the page.
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => useAgentSelectionStore.getState().select("agent-2"));
    act(() => result.current.sendMessage("hello"));

    expect(lastFrame().agent_id).toBe("agent-2");
  });

  it("adds the agent to the frame without disturbing the rest of it", () => {
    // `agent_id` is one more field, not a different frame. The model override
    // names a vault profile, and the run records which one answered.
    useAgentSelectionStore.getState().select("agent-1");

    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => {
      result.current.setModelProfile("profile-1");
      result.current.sendMessage("hello");
    });

    expect(lastFrame()).toMatchObject({
      message: "hello",
      agent_id: "agent-1",
      model_profile_id: "profile-1",
    });
  });
});

describe("useChat - attributing the answer", () => {
  it("credits the answer to the agent the turn was sent to", () => {
    useAgentSelectionStore.getState().select("agent-1");

    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("hello"));
    // Switching while the answer streams must not re-credit a run that is
    // already under way to the newly picked agent.
    act(() => useAgentSelectionStore.getState().select("agent-2"));
    receive("model_request_start", {});

    const assistant = useChatStore.getState().messages.find((m) => m.role === "assistant");
    expect(assistant?.agentId).toBe("agent-1");
  });

  it("leaves an assistant turn unattributed", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("hello"));
    receive("model_request_start", {});

    const assistant = useChatStore.getState().messages.find((m) => m.role === "assistant");
    expect(assistant?.agentId).toBeUndefined();
  });
});

/**
 * The stream a turn arrives as.
 *
 * The backend sends one frame per thing that happened, and this is what turns
 * them into a message. Two ids are held in refs rather than state because the
 * handler reads them synchronously - a `model_request_start` and a `text_delta`
 * can land in the same server flush, and the delta has to see the id the start
 * just created rather than waiting for React to re-render.
 */
describe("useChat - the streamed answer", () => {
  it("opens an empty message when the model starts, and fills it as text arrives", () => {
    renderHook(() => useChat(), { wrapper });

    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Refunds " });
    receive("text_delta", { index: 1, content: "run to thirty days." });

    expect(streaming()).toMatchObject({
      content: "Refunds run to thirty days.",
      isStreaming: true,
    });
  });

  it("ignores a delta that arrives before any message was opened", () => {
    // A frame from a turn that was already finished and cleared.
    renderHook(() => useChat(), { wrapper });

    receive("text_delta", { index: 0, content: "orphan" });

    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("opens a message for reasoning that arrives first", () => {
    // A thinking model publishes its trace before any text, and there is nothing
    // to attach it to yet.
    renderHook(() => useChat(), { wrapper });

    receive("thinking_delta", { index: 0, content: "Checking the policy." });

    expect(streaming()?.thinking).toBe("Checking the policy.");
  });

  it("keeps reasoning on the message already open", () => {
    renderHook(() => useChat(), { wrapper });

    receive("model_request_start", {});
    receive("thinking_delta", { index: 0, content: "Checking." });

    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(streaming()?.thinking).toBe("Checking.");
  });

  it("closes the previous message when a second one opens", () => {
    // One turn can produce several messages; the first must stop rendering as
    // still streaming.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "first" });

    receive("model_request_start", {});

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(2);
    expect(messages[0]?.isStreaming).toBe(false);
  });

  it("shows a tool call and then its result, in the timeline", () => {
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});

    receive("tool_call", { tool_call_id: "tc-1", tool_name: "search_documents", args: { q: "x" } });
    expect(streaming()?.toolCalls?.[0]).toMatchObject({ id: "tc-1", status: "running" });

    receive("tool_result", { tool_call_id: "tc-1", content: "3 passages" });
    expect(streaming()?.toolCalls?.[0]).toMatchObject({
      status: "completed",
      result: "3 passages",
    });
  });

  it("ignores a tool frame with no message open", () => {
    renderHook(() => useChat(), { wrapper });

    receive("tool_call", { tool_call_id: "tc-1", tool_name: "x", args: {} });
    receive("tool_result", { tool_call_id: "tc-1", content: "y" });

    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("takes the answer from the final frame when nothing was streamed", () => {
    // A model that answers in one piece sends no deltas at all.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});

    receive("final_result", { output: "Thirty days." });

    expect(streaming()).toMatchObject({ content: "Thirty days.", isStreaming: false });
  });

  it("does not repeat the answer that was already streamed", () => {
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Thirty days." });

    receive("final_result", { output: "Thirty days." });

    expect(streaming()?.content).toBe("Thirty days.");
  });

  it("stops processing on the final frame even with nothing open", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("final_result", { output: "" });

    expect(result.current.isProcessing).toBe(false);
  });

  it("ignores the narration frames the server sends around every turn", () => {
    // The six frames `agent_session.py` sends that this hook deliberately does not
    // read. They must pass through without opening a message, because a turn that
    // began with one of these would show an empty assistant bubble before the model
    // said anything.
    //
    // This replaces a test that replayed `llm_started` and `llm_completed` - two
    // frames no backend surface has ever sent. It passed, which was the problem: it
    // made a `case` arm nothing could reach look covered and load-bearing.
    renderHook(() => useChat(), { wrapper });

    receive("user_prompt", { content: "How long?" });
    receive("user_prompt_processed", { prompt: "How long?" });
    receive("part_start", { index: 0, part_type: "TextPart" });
    receive("call_tools_start", {});
    receive("tool_call_delta", { index: 0, args_delta: '{"q":' });
    receive("final_result_start", { tool_name: null });

    expect(useChatStore.getState().messages).toEqual([]);
  });
});

describe("useChat - failures and interruptions", () => {
  it("writes the error into the message being streamed", () => {
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Let me check." });

    receive("error", { message: "Budget exceeded" });

    expect(streaming()).toMatchObject({ isStreaming: false });
    expect(streaming()?.content).toContain("❌ Error: Budget exceeded");
  });

  it("says an error happened even when the server named no reason", () => {
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});

    receive("error", { message: "" });

    expect(streaming()?.content).toContain("Unknown error");
  });

  it("stops processing on an error with nothing open", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("error", { message: "Budget exceeded" });

    expect(result.current.isProcessing).toBe(false);
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("stops a turn on request and clears everything waiting on it", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      action_requests: [{ id: "ar-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });

    act(() => result.current.stopGeneration());

    expect(frame(0)).toEqual({ type: "stop" });
    expect(streaming()?.isStreaming).toBe(false);
    expect(result.current.isProcessing).toBe(false);
    expect(result.current.pendingApproval).toBeNull();
    expect(result.current.pendingQuestions).toBeNull();
  });

  it("stops cleanly with no turn in flight", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.stopGeneration());

    expect(frame(0)).toEqual({ type: "stop" });
  });
});

describe("useChat - streaming a delegation", () => {
  /** A `subagent_start`, replayed the way the server sends one. */
  function startDelegation(taskId: string, subagent = "researcher", mode = "sync"): void {
    receive("subagent_start", {
      kind: "subagent_start",
      task_id: taskId,
      subagent,
      depth: 0,
      mode,
      prompt: "find three papers",
      parent_task_id: null,
    });
  }

  it("opens a panel per delegation and fills it from its own frames", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");
    receive("subagent_text_delta", {
      kind: "subagent_text_delta",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      delta: "found three",
    });

    expect(result.current.delegations).toHaveLength(1);
    expect(result.current.delegations[0]).toMatchObject({
      taskId: "t1",
      subagent: "researcher",
      status: "running",
      text: "found three",
    });
  });

  it("keeps a delegation's panel alive past the turn's own complete", () => {
    // The bug this exists to prevent. A background delegation reports *after* the
    // parent's answer, and `complete` is what clears the streaming message - so a
    // panel hung off that message loses the last thing a specialist said, silently,
    // in exactly the case the delegation was started for.
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    startDelegation("t1", "researcher", "async");

    receive("complete", { conversation_id: null, usage: null });
    receive("subagent_text_delta", {
      kind: "subagent_text_delta",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      delta: "the last word",
    });
    receive("subagent_complete", {
      kind: "subagent_complete",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      status: "completed",
      run_id: null,
      cost_usd: 0.0042,
      input_tokens: 10,
      output_tokens: 5,
      error: null,
    });

    expect(result.current.delegations[0]).toMatchObject({
      status: "completed",
      text: "the last word",
      costUsd: 0.0042,
    });
  });

  it("closes a delegate's panel into a waiting state when it stops for a person", () => {
    // A sync delegate that parks on an approval sends `subagent_awaiting_approval`
    // and no `subagent_complete` until the person decides. The panel must stop
    // reading "working" rather than spin for the length of the wait.
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");

    receive("subagent_awaiting_approval", {
      kind: "subagent_awaiting_approval",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
    });

    expect(result.current.delegations[0]?.status).toBe("awaiting_approval");
  });

  it("closes an unfinished delegation when the run was cancelled", () => {
    // The cancelled path sends `stopped` (`AgentSession._run_turn`) and nothing
    // more is coming, so a panel left running would spin forever. The frontend
    // never read this field before.
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");

    receive("complete", { conversation_id: null, stopped: true });

    expect(result.current.delegations[0]?.status).toBe("cancelled");
  });

  it("closes an unfinished delegation when the turn failed", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");

    receive("error", { message: "Budget exceeded" });

    expect(result.current.delegations[0]?.status).toBe("cancelled");
  });

  it("closes an unfinished delegation when the person presses stop", () => {
    // Optimistic on purpose: the server's `complete` may never arrive, because the
    // socket can be what went away.
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");

    act(() => result.current.stopGeneration());

    expect(result.current.delegations[0]?.status).toBe("cancelled");
  });

  it("replaces the previous turn's panels when the next message goes out", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");
    receive("complete", { conversation_id: null });

    act(() => result.current.sendMessage("and now something else"));

    expect(result.current.delegations).toEqual([]);
  });

  it("drops a frame for a delegation it has no panel for", () => {
    // A background delegation of the previous turn reporting after the panels were
    // replaced. A panel invented from a delta has no delegate name and no prompt.
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("subagent_text_delta", {
      kind: "subagent_text_delta",
      task_id: "gone",
      subagent: "researcher",
      depth: 0,
      delta: "nobody is listening",
    });

    expect(result.current.delegations).toEqual([]);
  });

  it("leaves the previous conversation's delegations behind when another is opened", () => {
    // Sending a message was the only thing that cleared them, so completing a
    // delegated turn in one conversation and then picking another from the sidebar
    // drew that conversation's specialists, their briefs and their costs under a
    // transcript they had nothing to do with.
    useConversationStore.getState().setCurrentConversationId("c-a");
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");
    receive("complete", { conversation_id: null });
    expect(result.current.delegations).toHaveLength(1);

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-b");
    });

    expect(result.current.delegations).toEqual([]);
  });

  it("keeps the panels of the turn that just learned its conversation id", () => {
    // The first turn of a new thread is told the id by `conversation_created` while
    // it is still streaming. That is this conversation being named, not another being
    // opened, and clearing there would take the panels of the turn on screen.
    const { result } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");

    receive("conversation_created", { conversation_id: "c-new" });

    expect(result.current.delegations).toHaveLength(1);
  });

  it("leaves the previous tenant's delegations behind when the organization moves", () => {
    useOrgStore.setState({ activeOrgId: "org-a" });
    const { result, rerender } = renderHook(() => useChat(), { wrapper });
    startDelegation("t1");
    expect(result.current.delegations).toHaveLength(1);

    act(() => {
      useOrgStore.setState({ activeOrgId: "org-b" });
    });
    rerender();

    expect(result.current.delegations).toEqual([]);
  });
});

describe("useChat - the conversation a turn belongs to", () => {
  it("adopts the conversation the backend created, and puts it in the address bar", () => {
    // So a refresh mid-turn lands back on the same thread.
    const onConversationCreated = vi.fn();
    renderHook(() => useChat({ onConversationCreated }), { wrapper });
    receive("model_request_start", {});

    receive("conversation_created", { conversation_id: "c-new" });

    expect(useConversationStore.getState().currentConversationId).toBe("c-new");
    expect(window.location.search).toBe("?id=c-new");
    expect(onConversationCreated).toHaveBeenCalledWith("c-new");
    expect(streaming()?.conversationId).toBe("c-new");
  });

  it("stamps a new message with the conversation already open", () => {
    useConversationStore.getState().setCurrentConversationId("c-1");
    renderHook(() => useChat(), { wrapper });

    receive("model_request_start", {});

    expect(streaming()?.conversationId).toBe("c-1");
  });

  it("falls back to the conversation the caller passed", () => {
    renderHook(() => useChat({ conversationId: "c-prop" }), { wrapper });

    receive("model_request_start", {});

    expect(streaming()?.conversationId).toBe("c-prop");
  });

  it("swaps the temporary id for the one the database gave it", () => {
    // Every later action - a rating, a share - addresses the message by id.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});

    receive("message_saved", { message_id: "m-real" });

    expect(streaming()).toMatchObject({ id: "m-real", isTemporaryId: false });
  });

  it("keeps what the last turn cost, and does not clear it when a turn reports none", () => {
    // A turn the server could not measure must not blank a number the previous
    // one legitimately reported - the strip would flicker to nothing mid-chat.
    const { result } = renderHook(() => useChat(), { wrapper });
    expect(result.current.lastUsage).toBeNull();

    receive("complete", {
      usage: {
        input_tokens: 1200,
        output_tokens: 300,
        cost_usd: 0.0125,
        budget_percent: null,
        sandbox: null,
      },
    });
    expect(result.current.lastUsage).toMatchObject({ input_tokens: 1200 });

    receive("complete", {});
    expect(result.current.lastUsage).toMatchObject({ input_tokens: 1200 });
  });

  it("still finds the message after it has been given its real id", () => {
    // `message_saved` renames the streaming message, and everything after it -
    // the cost, an error - addresses the message through the ref. A ref left
    // holding the temporary id addresses a message that no longer exists, so the
    // cost was written to nothing and appeared only after a reload.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("message_saved", { message_id: "m-real" });

    receive("complete", {
      usage: {
        input_tokens: 4055,
        output_tokens: 24,
        cost_usd: 0.0012,
        budget_percent: null,
        agent_budget_percent: null,
        sandbox: null,
      },
    });

    expect(streaming()).toMatchObject({ id: "m-real" });
    expect(streaming()?.usage).toMatchObject({ input_tokens: 4055 });
  });

  it("credits the cost to the conversation it was passed, before the store catches up", () => {
    // The page knows which thread it opened before the store does, and a cost
    // attributed to `null` would be shown under whatever came next.
    const { result } = renderHook(() => useChat({ conversationId: "c-passed" }), { wrapper });

    receive("complete", {
      usage: {
        input_tokens: 5,
        output_tokens: 5,
        cost_usd: 0.001,
        budget_percent: null,
        agent_budget_percent: null,
        sandbox: null,
      },
    });

    expect(result.current.lastUsage).toMatchObject({ input_tokens: 5 });
  });

  it("does not report one conversation's cost under another", () => {
    // The bare value survived a switch, so the strip showed the thread somebody had
    // just left. Keyed on the conversation, it simply is not returned.
    useConversationStore.getState().setCurrentConversationId("c-1");
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("complete", {
      usage: {
        input_tokens: 1200,
        output_tokens: 300,
        cost_usd: 0.0125,
        budget_percent: null,
        agent_budget_percent: null,
        sandbox: null,
      },
    });
    expect(result.current.lastUsage).toMatchObject({ input_tokens: 1200 });

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-2");
    });

    expect(result.current.lastUsage).toBeNull();
  });

  it("records the cost on the answer that cost it, not only under the input", () => {
    // The strip only ever describes the last turn, so in a long conversation
    // there is no way to see which answer was the expensive one.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});

    receive("complete", {
      usage: {
        input_tokens: 1200,
        output_tokens: 300,
        cost_usd: 0.0125,
        budget_percent: null,
        agent_budget_percent: null,
        sandbox: null,
      },
    });

    expect(streaming()?.usage).toMatchObject({ input_tokens: 1200, output_tokens: 300 });
  });

  it("finds the message to rename when the turn has already completed", () => {
    // `complete` clears the id, and `message_saved` can arrive after it.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("complete", {});

    receive("message_saved", { message_id: "m-real" });

    expect(useChatStore.getState().messages[0]).toMatchObject({
      id: "m-real",
      isTemporaryId: false,
    });
  });

  it("renames nothing when there is no temporary message to rename", () => {
    renderHook(() => useChat(), { wrapper });
    receive("complete", {});

    receive("message_saved", { message_id: "m-real" });

    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("nudges the billing view when a turn completes, because it just spent money", () => {
    const listener = vi.fn();
    window.addEventListener("billing:refresh", listener);
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("complete", {});

    expect(listener).toHaveBeenCalled();
    expect(result.current.isProcessing).toBe(false);
    window.removeEventListener("billing:refresh", listener);
  });
});

describe("useChat - approvals and questions", () => {
  it("surfaces the tools waiting on a person, and resolves their cards", async () => {
    // The card used to spin forever: a parked call produces no `tool_result`
    // until somebody decides, so "running" is a state it never leaves.
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_name: "send_email", args: {}, tool_call_id: "tc-1" });

    receive("tool_approval_required", {
      run_id: "r-1",
      action_requests: [
        { id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: { to: "a@b.c" } },
      ],
      review_configs: [{ tool_name: "send_email", allow_edit: false }],
    });

    expect(result.current.pendingApproval).toMatchObject({
      actionRequests: [{ id: "ar-1", tool_name: "send_email" }],
      runId: "r-1",
    });
    const card = streaming()?.parts?.find((part) => part.type === "tool");
    expect(card?.toolCall?.status).toBe("awaiting_approval");
  });

  it("still surfaces an approval with no message open", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("tool_approval_required", {
      run_id: "r-1",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });

    expect(result.current.pendingApproval).not.toBeNull();
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("records each decision on its own approval row, then resumes once", async () => {
    // Once, after all of them: the run continues when nothing is left parked, and
    // resuming per decision would start it while calls it has not heard about are
    // still waiting.
    post.mockResolvedValue({});
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [
        { id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} },
        { id: "ar-2", tool_call_id: "tc-2", tool_name: "delete_row", args: {} },
      ],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }, { type: "reject" }]);
    });

    expect(post.mock.calls).toEqual([
      ["/approvals/ar-1", { approved: true }],
      ["/approvals/ar-2", { approved: false }],
      ["/runs/r-9/resume"],
    ]);
    expect(result.current.pendingApproval).toBeNull();
  });

  it("shows what the resumed run answered, rather than discarding it", async () => {
    // `resume_run` executes the agent and returns its output - over HTTP, to whoever
    // asked, never over this conversation's socket. Throwing that away is what made an
    // approval look like it had done nothing: the panel vanished, a toast said the run
    // was continuing, and the transcript then sat unchanged until a page reload.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Done - 3 rows deleted.", status: "completed" })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "delete_row", args: {} }],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const answers = useChatStore
      .getState()
      .messages.filter((message) => message.role === "assistant");
    expect(answers.at(-1)?.content).toBe("Done - 3 rows deleted.");
  });

  it("closes a parked delegate's panel once the run is approved and resumes", async () => {
    // The crux of agenticos#173. A sync delegate parks on an approval and its panel
    // reads "waiting for approval". The resume runs over HTTP - no delegation frames
    // reach this socket - so without reconciling the panel from its answer it would
    // read "waiting" forever, under a transcript already showing the resumed reply.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Sent.", status: "completed" })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("subagent_start", {
      kind: "subagent_start",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      mode: "sync",
      prompt: "send the summary",
      parent_task_id: null,
    });
    receive("subagent_text_delta", {
      kind: "subagent_text_delta",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      delta: "drafting",
    });
    receive("subagent_awaiting_approval", {
      kind: "subagent_awaiting_approval",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
    });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });
    expect(result.current.delegations[0]?.status).toBe("awaiting_approval");

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    // Terminal now - and it still holds what it streamed before it parked.
    expect(result.current.delegations[0]).toMatchObject({ status: "completed", text: "drafting" });
  });

  it("leaves a parked delegate waiting when the resume parks again", async () => {
    // A continuation can stop on a fresh decision. The delegate is still waiting, so
    // its panel must not be closed to a terminal state it has not reached.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "", status: "awaiting_approval" })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("subagent_start", {
      kind: "subagent_start",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      mode: "sync",
      prompt: "send the summary",
      parent_task_id: null,
    });
    receive("subagent_awaiting_approval", {
      kind: "subagent_awaiting_approval",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
    });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(result.current.delegations[0]?.status).toBe("awaiting_approval");
  });

  it("closes a parked delegate's panel when the resume's continuation fails", async () => {
    // agenticos#262. The approval is granted and the continuation *raises*: the
    // resume does not return, so there is no `status` to reconcile from - but the
    // backend recorded the run `failed` and sent it in the error body. Without
    // reading it, the panel reads "waiting for approval" forever, on a run that can
    // no longer be resumed. It must close to `failed`, and the decided approval must
    // not come back for a retry that would only 400.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.reject(
            new ApiError(500, "The run failed while continuing after approval", {
              error: {
                code: "RUN_EXECUTION_FAILED",
                message: "The run failed while continuing after approval",
                details: { run_id: "r-9", status: "failed" },
              },
            }),
          )
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("subagent_start", {
      kind: "subagent_start",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      mode: "sync",
      prompt: "send the summary",
      parent_task_id: null,
    });
    receive("subagent_awaiting_approval", {
      kind: "subagent_awaiting_approval",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
    });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });
    expect(result.current.delegations[0]?.status).toBe("awaiting_approval");

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(result.current.delegations[0]?.status).toBe("failed");
    // Not restored: the run is terminal, so a retry cannot succeed.
    expect(result.current.pendingApproval).toBeNull();
  });

  it("adds nothing when the resumed run answered with nothing", async () => {
    // A refusal resumes into an empty output, and an empty bubble in the transcript
    // is worse than no bubble.
    post.mockResolvedValue({ run_id: "r-9", output: "", status: "completed" });
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "delete_row", args: {} }],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "reject" }]);
    });

    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("puts the panel back when a decision could not be recorded", async () => {
    // A decision that failed to record is a run still parked, and a panel that
    // vanished is a person believing they unblocked it.
    post.mockRejectedValue(new Error("403 Forbidden"));
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: {} }],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(result.current.pendingApproval).not.toBeNull();
  });

  it("decides nothing when there was nothing parked", async () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(post).not.toHaveBeenCalled();
  });

  it("ignores a decision list shorter than what is waiting", async () => {
    // Rather than reading `undefined` as a refusal, which would reject a call
    // nobody decided about.
    post.mockResolvedValue({});
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [
        { id: "ar-1", tool_call_id: "tc-1", tool_name: "a", args: {} },
        { id: "ar-2", tool_call_id: "tc-2", tool_name: "b", args: {} },
      ],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(post.mock.calls).toEqual([
      ["/approvals/ar-1", { approved: true }],
      ["/runs/r-9/resume"],
    ]);
  });

  it("surfaces the questions an agent asked, filling in what it left out", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("ask_user", {
      questions: [{ question: "Which invoice?", allow_custom: true }],
    });

    expect(result.current.pendingQuestions).toEqual([
      { question: "Which invoice?", options: [], allowCustom: true },
    ]);
  });

  it("surfaces an empty list rather than nothing when the frame carries none", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("ask_user", {});

    expect(result.current.pendingQuestions).toEqual([]);
  });

  it("sends the answers and closes the prompt", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("ask_user", {
      questions: [{ question: "Which?", options: ["a"], allow_custom: false }],
    });

    act(() => result.current.sendAskUserResponses([{ answer: "a", skipped: false }]));

    expect(result.current.pendingQuestions).toBeNull();
    expect(frame(0)).toEqual({
      type: "ask_user_response",
      answers: [{ answer: "a", skipped: false }],
    });
  });

  it("keeps the questions on screen when the socket is offline", () => {
    // Clearing them would lose the question with no way to answer it.
    socket.isConnected = false;
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("ask_user", { questions: [{ question: "Which?", options: [], allow_custom: true }] });

    act(() => result.current.sendAskUserResponses([{ answer: "a", skipped: false }]));

    expect(result.current.pendingQuestions).not.toBeNull();
    expect(sent).not.toHaveBeenCalled();
  });
});

describe("useChat - what goes out with a turn", () => {
  it("adds the person's own message and marks the turn in flight", () => {
    const { result } = renderHook(() => useChat({ conversationId: "c-1" }), { wrapper });

    act(() => result.current.sendMessage("How long?", ["f-1"], [{ id: "f-1" } as never]));

    expect(useChatStore.getState().messages[0]).toMatchObject({
      role: "user",
      content: "How long?",
      conversationId: "c-1",
      fileIds: ["f-1"],
    });
    expect(result.current.isProcessing).toBe(true);
    expect(frame(0)).toMatchObject({
      message: "How long?",
      conversation_id: "c-1",
      file_ids: ["f-1"],
    });
  });

  it("sends a null conversation id for the first turn of a new thread", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.sendMessage("hello"));

    expect(frame(0)).toMatchObject({ conversation_id: null });
    expect(frame(0)).not.toHaveProperty("file_ids");
  });

  it("carries the per-turn model overrides, and only when they are set", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.sendMessage("first"));
    expect(frame(0)).not.toHaveProperty("model_profile_id");

    act(() => {
      result.current.setModelProfile("p-1");
      result.current.setTemperature(0.2);
      result.current.setThinkingEffort("high");
    });
    receive("complete", {});
    act(() => result.current.sendMessage("second"));

    expect(frame(1)).toMatchObject({
      model_profile_id: "p-1",
      temperature: 0.2,
      thinking_effort: "high",
    });
  });

  it("keeps a temperature of zero, which is a deliberate setting", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.setTemperature(0));

    act(() => result.current.sendMessage("hello"));

    expect(frame(0)).toMatchObject({ temperature: 0 });
  });
});

describe("useChat - the outbound queue", () => {
  it("queues what is typed while the agent is busy, and drains it when it is idle", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("first"));
    expect(result.current.isProcessing).toBe(true);

    act(() => result.current.sendMessage("second"));
    expect(result.current.queuedMessages.map((entry) => entry.content)).toEqual(["second"]);
    expect(sent).toHaveBeenCalledTimes(1);

    receive("complete", {});
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(result.current.queuedMessages).toEqual([]);
    expect(frame(1)).toMatchObject({ message: "second" });
    vi.useRealTimers();
  });

  it("throws away a queued message when the organization changes", () => {
    // It waits in this hook's own state until the socket returns, so neither
    // dropping the query cache nor resetting the stores reaches it - the
    // message was typed in one organization and would have been sent as the
    // next one, once their socket connected.
    socket.isConnected = false;
    useOrgStore.setState({ activeOrgId: "org-a" });
    const { result, rerender } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("meant for org A"));
    expect(result.current.queuedMessages).toHaveLength(1);

    act(() => {
      useOrgStore.setState({ activeOrgId: "org-b" });
    });
    rerender();

    expect(result.current.queuedMessages).toEqual([]);
  });

  it("queues what is typed while the socket is offline", () => {
    socket.isConnected = false;
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.sendMessage("offline"));

    expect(result.current.queuedMessages).toHaveLength(1);
    expect(sent).not.toHaveBeenCalled();
  });

  it("cancels one queued message and keeps the rest", () => {
    socket.isConnected = false;
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("one"));
    act(() => result.current.sendMessage("two"));

    act(() => result.current.cancelQueued(result.current.queuedMessages[0]!.id));

    expect(result.current.queuedMessages.map((entry) => entry.content)).toEqual(["two"]);
  });

  it("clears the whole queue", () => {
    socket.isConnected = false;
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("one"));
    act(() => result.current.sendMessage("two"));

    act(() => result.current.clearQueued());

    expect(result.current.queuedMessages).toEqual([]);
  });
});

describe("useChat - the socket it opens", () => {
  it("authenticates through the subprotocol rather than the URL", () => {
    // A token in the query string ends up in access logs and Referer headers.
    renderHook(() => useChat(), { wrapper });

    expect(socket.protocols).toEqual(["access_token.t-1", "chat"]);
    expect(socket.url).not.toContain("t-1");
  });

  it("opens no socket at all before the token is in memory", () => {
    // A token-less socket is refused by the server, which used to produce a
    // reconnect storm on every page load.
    useAuthStore.setState({ accessToken: null });

    renderHook(() => useChat(), { wrapper });

    expect(socket.protocols).toBeUndefined();
    expect(connect).not.toHaveBeenCalled();
  });

  it("carries the active organization in the URL, because a handshake takes no headers", () => {
    useOrgStore.setState({ activeOrgId: "org 7" });

    renderHook(() => useChat(), { wrapper });

    expect(socket.url).toContain("organization_id=org%207");
  });

  it("refreshes the token when the socket drops, once", async () => {
    // A dropped socket is usually a stale token; one in-flight `/auth/me` is
    // enough, and one per backoff attempt would stampede it.
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ access_token: "t-2" }) });
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useChat(), { wrapper });

    await act(async () => {
      socket.onClose?.();
      socket.onClose?.();
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().accessToken).toBe("t-2");
    vi.unstubAllGlobals();
  });

  it("keeps the token it has when the refresh is refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    renderHook(() => useChat(), { wrapper });

    await act(async () => {
      socket.onClose?.();
      await Promise.resolve();
    });

    expect(useAuthStore.getState().accessToken).toBe("t-1");
    vi.unstubAllGlobals();
  });

  it("keeps the token when the refresh answers without one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
    );
    renderHook(() => useChat(), { wrapper });

    await act(async () => {
      socket.onClose?.();
      await Promise.resolve();
    });

    expect(useAuthStore.getState().accessToken).toBe("t-1");
    vi.unstubAllGlobals();
  });

  it("survives a refresh that could not be made at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderHook(() => useChat(), { wrapper });

    await act(async () => {
      socket.onClose?.();
      await Promise.resolve();
    });

    expect(useAuthStore.getState().accessToken).toBe("t-1");
    vi.unstubAllGlobals();
  });

  it("closes the socket when the chat goes away", () => {
    const { unmount } = renderHook(() => useChat(), { wrapper });

    unmount();

    expect(disconnect).toHaveBeenCalled();
  });
});
