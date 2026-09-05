import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
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
const { post, get } = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { post, get } }));
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
 * message queued in one organization must not be sent as another. It reads the
 * caller's permissions the same way, for whether a reloaded parked run may have
 * its approval panel rebuilt.
 */
function makeWrapper(permissions: string[] = []) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    // Seeded rather than fetched: these tests count requests, and an
    // organizations or permissions query going out would be a request none of
    // them made.
    client.setQueryData(qk.organizations.list(), []);
    client.setQueryData(qk.organizations.permissions("current"), {
      organization_id: "org-1",
      role: "member",
      is_app_admin: false,
      permissions: permissions.map((permission) => ({ permission, scope: "all" })),
    });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const wrapper = makeWrapper();
/** The same wrapper for a caller who may decide approvals. */
const decider = makeWrapper(["approvals:decide"]);

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

/** A stored assistant turn whose run is parked - what a reloaded conversation holds. */
function parkedTurn() {
  return {
    id: "m-1",
    role: "assistant" as const,
    content: "",
    timestamp: new Date(),
    conversationId: "c-1",
    runId: "r-1",
    toolCalls: [{ id: "tc-1", name: "send_email", args: {}, status: "awaiting_approval" as const }],
  };
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

  it("keeps one turn in one message however many requests it takes", () => {
    // A multi-step turn makes a request per tool round. Opening a message on each
    // one split a single answer into a bubble per round, with the tool steps
    // scattered one per message - so nothing grouped them onto a rail, and the
    // stored turn (one row) could only ever match one of them, which is why a
    // reload showed something different from what was watched.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Below are the charts." });
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "create_chart", args: {} });
    receive("tool_result", { tool_call_id: "tc-1", content: "{}" });

    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Done." });

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]?.parts?.map((part) => part.type)).toEqual(["text", "tool", "text"]);
  });

  it("opens a second message for the next turn, and closes the first", () => {
    // Across turns the split is right. `final_result` ends the answer and
    // `complete` ends the turn, which is what lets the next request open its own
    // message rather than appending to this one.
    renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "first" });
    receive("final_result", { output: "first" });
    receive("complete", {});

    receive("model_request_start", {});

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(2);
    expect(messages[0]?.isStreaming).toBe(false);
  });

  it("does not append a new question's answer to a turn the socket abandoned", () => {
    // A dropped connection sends no `complete`, so nothing clears the open turn.
    // With one message per turn that left the ref pointing at the abandoned
    // answer, and the next one was appended to it - two turns in one bubble, with
    // the first still rendering a cursor. Asking again is the boundary that holds
    // whatever the socket did.
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "half an answ" });

    act(() => result.current.sendMessage("are you still there?"));
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Yes." });

    const messages = useChatStore.getState().messages;
    expect(messages.map((message) => message.role)).toEqual(["assistant", "user", "assistant"]);
    expect(messages[0]?.isStreaming).toBe(false);
    expect(messages[0]?.content).toBe("half an answ");
    expect(messages[2]?.content).toBe("Yes.");
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

  it("refreshes the Memory tab when the agent finishes writing memory", () => {
    // The Memory tab is a separate view the chat cannot see; a write in chat must
    // invalidate that agent's memory queries so the tab refetches rather than
    // showing a stale list.
    useAgentSelectionStore.setState({ selectedAgentId: "agent-1" });
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => {
      void result.current.sendMessage("remember it");
    });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-m", tool_name: "write_memory", args: {} });
    receive("tool_result", { tool_call_id: "tc-m", content: "Saved memory 'x'." });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.memory.all("agent-1") });
    invalidate.mockRestore();
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

  it("re-reads what the thread has cost once a turn has added to it", async () => {
    // The total is read when the transcript loads, so without this it is a
    // conversation out of date by the second message. Re-read rather than added
    // to: a run that parked reports its cost so far and the resume reports the
    // run's total, so the obvious arithmetic counts the approved half twice.
    useConversationStore.getState().setCurrentConversationId("c-1");
    get.mockResolvedValueOnce({
      cost: { input_tokens: 40, output_tokens: 4, cost_usd: "0.9", cost_is_partial: false },
    });
    renderHook(() => useChat(), { wrapper });

    receive("complete", {
      usage: {
        input_tokens: 1200,
        output_tokens: 300,
        cost_usd: 0.0125,
        budget_percent: null,
        sandbox: null,
      },
    });

    await waitFor(() =>
      expect(useConversationStore.getState().currentCost).toMatchObject({ input_tokens: 40 }),
    );
    expect(get).toHaveBeenCalledWith("/conversations/c-1/messages?skip=0&limit=1");
  });

  it("leaves the total alone when the re-read fails", async () => {
    // Stale is not wrong, and losing an answer to a failed accounting read would
    // be the worse trade.
    useConversationStore.getState().setCurrentConversationId("c-1");
    useConversationStore.getState().setCurrentMessages([], {
      input_tokens: 7,
      output_tokens: 1,
      cost_usd: "0.1",
      cost_is_partial: false,
    });
    get.mockRejectedValueOnce(new Error("gone"));
    renderHook(() => useChat(), { wrapper });

    receive("complete", {
      usage: {
        input_tokens: 1,
        output_tokens: 1,
        cost_usd: 0.01,
        budget_percent: null,
        sandbox: null,
      },
    });

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(useConversationStore.getState().currentCost).toMatchObject({ input_tokens: 7 });
  });

  it("asks for nothing when a turn finished outside any conversation", () => {
    renderHook(() => useChat(), { wrapper });

    receive("complete", {
      usage: {
        input_tokens: 1,
        output_tokens: 1,
        cost_usd: 0.01,
        budget_percent: null,
        sandbox: null,
      },
    });

    expect(get).not.toHaveBeenCalled();
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

describe("useChat - the summary of its own history", () => {
  it("reports a summary while it is being written", () => {
    // Compaction runs between two of the turn's model requests, where nothing
    // else streams: no token, no tool step. Without this frame the screen is
    // indistinguishable from a broken one, and reloading it cancels the turn.
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("compaction_started", {
      kind: "compaction_started",
      messages_before: 62,
      messages_after: null,
    });

    expect(result.current.compacting).toMatchObject({ messages_before: 62 });
  });

  it("clears it when the summary finishes", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("compaction_started", {
      kind: "compaction_started",
      messages_before: 62,
      messages_after: null,
    });

    receive("compaction_finished", {
      kind: "compaction_finished",
      messages_before: 62,
      messages_after: 9,
    });

    expect(result.current.compacting).toBeNull();
  });

  it("keeps a window that cannot work on screen after the turn", () => {
    // A setting, not a state: clearing it when the turn ends would flash the one
    // message explaining why nothing happened.
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("compaction_impossible", {
      kind: "compaction_impossible",
      messages_before: null,
      messages_after: null,
      overhead_tokens: 3_843,
      window_tokens: 5_000,
    });
    receive("complete", {});

    expect(result.current.compactionImpossible).toMatchObject({ overhead_tokens: 3_843 });
  });

  it("drops the warning once a summary actually runs", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("compaction_impossible", {
      kind: "compaction_impossible",
      messages_before: null,
      messages_after: null,
      overhead_tokens: 3_843,
      window_tokens: 5_000,
    });

    receive("compaction_started", {
      kind: "compaction_started",
      messages_before: 8,
      messages_after: null,
    });

    expect(result.current.compactionImpossible).toBeNull();
  });

  it("clears it when the turn ends without one", () => {
    // A run that failed between the two frames would otherwise leave the notice
    // up until the next message, over a composer somebody is typing into.
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("compaction_started", {
      kind: "compaction_started",
      messages_before: 62,
      messages_after: null,
    });

    receive("complete", {});

    expect(result.current.compacting).toBeNull();
  });

  it("leaves neither frame behind when another conversation is opened", () => {
    // Both survived a conversation switch: switch away mid-summary and
    // "Summarising…" drew over the thread just opened, and the "cannot run"
    // warning describes one agent's window against another's.
    useConversationStore.getState().setCurrentConversationId("c-a");
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("compaction_started", {
      kind: "compaction_started",
      messages_before: 62,
      messages_after: null,
    });
    receive("compaction_impossible", {
      kind: "compaction_impossible",
      messages_before: null,
      messages_after: null,
      overhead_tokens: 3_843,
      window_tokens: 5_000,
    });

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-b");
    });

    expect(result.current.compacting).toBeNull();
    expect(result.current.compactionImpossible).toBeNull();
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

  it("re-opens the panel when the continuation parks again", async () => {
    // A resume runs the agent, and the agent can reach a second gated call. Nothing
    // announces that here - the continuation runs over HTTP, so no
    // `tool_approval_required` frame arrives - so the panel closed on a run that was
    // still blocked, and the only way to finish it was the approvals queue on
    // another page. Three approvals in one conversation is what that looked like.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({
            run_id: "r-9",
            output: "",
            status: "awaiting_approval",
            parked: [
              { id: "ar-2", tool_call_id: "tc-2", tool_name: "execute", tool_args: { cmd: "ls" } },
            ],
          })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(result.current.pendingApproval?.actionRequests).toEqual([
      { id: "ar-2", tool_call_id: "tc-2", tool_name: "execute", args: { cmd: "ls" } },
    ]);
    expect(result.current.pendingApproval?.runId).toBe("r-9");
  });

  it("closes the panel when the continuation finished", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Done.", status: "completed", parked: [] })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    expect(result.current.pendingApproval).toBeNull();
  });

  it("credits the resumed answer to the agent that was answering", async () => {
    // The continuation is the second half of one turn. Added with no agent it
    // rendered under the generic robot with no name, so the same turn showed two
    // faces and the answer read as though a different agent had written it.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Six sheets.", status: "completed" })
        : Promise.resolve({}),
    );
    useAgentSelectionStore.setState({ selectedAgentId: "agent-jarvis" });
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.sendMessage("analyse this"));
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const answers = useChatStore
      .getState()
      .messages.filter((message) => message.role === "assistant");
    expect(answers.at(-1)?.agentId).toBe("agent-jarvis");
  });

  it("settles the parked step, which the end of the turn used to strand", async () => {
    // The park is followed immediately by `complete`, which ends the turn and clears
    // the "current message" ref - so every `updateToolCallPart` in the decision loop
    // was skipped, and the step sat at "waiting for approval" for the rest of the
    // session while the run had in fact resumed and answered. The turn the calls are
    // drawn in is captured when the approval arrives, not read off the ref later.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Done.", status: "completed" })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "execute", args: {} });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    // Completed, not `running`: the resumed call's result went to the HTTP response
    // rather than to this socket, so a step left running waits for a frame that
    // cannot arrive.
    const parked = useChatStore
      .getState()
      .messages.flatMap((message) => message.parts ?? [])
      .find((part) => part.toolCall?.id === "tc-1");
    expect(parked?.toolCall?.status).toBe("completed");
  });

  it("marks a refused call refused, on the turn it was drawn in", async () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "execute", args: {} });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "reject" }]);
    });

    const parked = useChatStore
      .getState()
      .messages.flatMap((message) => message.parts ?? [])
      .find((part) => part.toolCall?.id === "tc-1");
    expect(parked?.toolCall?.status).toBe("error");
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

  it("takes the approval panel off screen when another conversation is opened", () => {
    // It followed the reader from thread to thread. Worse than stale: *Approve*
    // still worked, so a call could be decided from under another agent's
    // transcript - and the step it settles lives in messages that are no longer
    // loaded, so nothing on screen changed to say it had been. The row is not lost
    // by clearing the panel; the approvals queue holds it.
    useConversationStore.getState().setCurrentConversationId("c-1");
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    expect(result.current.pendingApproval).not.toBeNull();

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-2");
    });

    expect(result.current.pendingApproval).toBeNull();
  });

  it("puts the approval panel back when a reloaded conversation is still parked", async () => {
    // The live `tool_approval_required` frame exists only for whoever was watching
    // when the run parked. The stored step says "waiting for approval" after a
    // reload, but the panel with the decision was gone, so the only way to finish
    // the run was the approvals queue on another page (#601).
    get.mockResolvedValue([
      { id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", tool_args: { to: "a@b.c" } },
      // A run parked before the tool-call mapping was stored has no id to
      // resolve a card with; the decision is still offered.
      { id: "ar-2", tool_call_id: null, tool_name: "execute", tool_args: {} },
    ]);
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage(parkedTurn());

    const { result } = renderHook(() => useChat(), { wrapper: decider });
    await act(async () => {});

    expect(get.mock.calls).toEqual([["/runs/r-1/parked"]]);
    expect(result.current.pendingApproval).toEqual({
      actionRequests: [
        { id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", args: { to: "a@b.c" } },
        { id: "ar-2", tool_call_id: "", tool_name: "execute", args: {} },
      ],
      reviewConfigs: [
        { tool_name: "send_email", allow_edit: false },
        { tool_name: "execute", allow_edit: false },
      ],
      runId: "r-1",
      messageId: "m-1",
    });
  });

  it("asks nothing without approvals:decide", async () => {
    // The endpoint is gated on the permission deciding takes, so a caller
    // without it would 403 on every reopened conversation. The stored step
    // still says the run is waiting; there is just no decision to offer.
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage(parkedTurn());

    const { result } = renderHook(() => useChat(), { wrapper });
    await act(async () => {});

    expect(get).not.toHaveBeenCalled();
    expect(result.current.pendingApproval).toBeNull();
  });

  it("asks about a run once, not on every store update", async () => {
    get.mockResolvedValue([]);
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage(parkedTurn());
    const { result } = renderHook(() => useChat(), { wrapper: decider });
    await act(async () => {});
    expect(result.current.pendingApproval).toBeNull();

    act(() => {
      useChatStore.getState().addMessage({
        id: "m-2",
        role: "user",
        content: "hello?",
        timestamp: new Date(),
      });
    });
    await act(async () => {});

    // Once for the run - and an answer of "nothing pending" leaves the panel
    // down rather than inventing one: the calls were decided somewhere else.
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("leaves a parked step from before runs were stamped on messages alone", async () => {
    // The step still reads "waiting for approval", but there is no run on the
    // message to ask about.
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage({ ...parkedTurn(), runId: undefined });

    const { result } = renderHook(() => useChat(), { wrapper: decider });
    await act(async () => {});

    expect(get).not.toHaveBeenCalled();
    expect(result.current.pendingApproval).toBeNull();
  });

  it("stays quiet when the parked rows cannot be read", async () => {
    // The approvals queue holds the same rows, so a panel that could not be
    // rebuilt is not worth an error over the transcript somebody is reading.
    get.mockRejectedValue(new Error("offline"));
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage(parkedTurn());

    const { result } = renderHook(() => useChat(), { wrapper: decider });
    await act(async () => {});

    expect(get).toHaveBeenCalledTimes(1);
    expect(result.current.pendingApproval).toBeNull();
  });

  it("drops an answer that lands after another conversation was opened", async () => {
    // The fetch can resolve on the far side of a conversation switch, and a
    // panel drawn under another transcript is the stale, actionable state the
    // switch effect exists to prevent - Approve would decide a call the person
    // is no longer looking at.
    let resolveParked!: (rows: unknown) => void;
    get.mockReturnValue(
      new Promise((resolve) => {
        resolveParked = resolve;
      }),
    );
    useConversationStore.getState().setCurrentConversationId("c-1");
    useChatStore.getState().addMessage(parkedTurn());
    const { result } = renderHook(() => useChat(), { wrapper: decider });
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(1);

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-2");
      // What the container does on a switch - the messages on screen are the
      // new conversation's.
      useChatStore.getState().clearMessages();
    });
    await act(async () => {
      resolveParked([{ id: "ar-1", tool_call_id: "tc-1", tool_name: "send_email", tool_args: {} }]);
    });

    expect(result.current.pendingApproval).toBeNull();
  });

  it("waits for the turn in flight before asking", async () => {
    // While a turn is processing the parked state on screen is the live one,
    // and the live frame is what will carry the panel.
    get.mockResolvedValue([]);
    useConversationStore.getState().setCurrentConversationId("c-1");
    const { result } = renderHook(() => useChat(), { wrapper: decider });
    act(() => result.current.sendMessage("do it"));
    act(() => {
      useChatStore.getState().addMessage(parkedTurn());
    });
    await act(async () => {});
    expect(get).not.toHaveBeenCalled();

    receive("complete", {});
    await act(async () => {});

    expect(get).toHaveBeenCalledTimes(1);
  });

  it("takes a pending question off screen when another conversation is opened", () => {
    // The same, one turn earlier: answering here would put words typed under one
    // transcript into a turn belonging to another.
    useConversationStore.getState().setCurrentConversationId("c-1");
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("ask_user", {
      questions: [{ question: "Which sheet?", options: ["Plan"], allow_custom: true }],
    });
    expect(result.current.pendingQuestions).not.toBeNull();

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-2");
    });

    expect(result.current.pendingQuestions).toBeNull();
  });

  it("keeps the panel through the turn that creates its own conversation", () => {
    // A first message parks on an approval: `conversation_created` arrives mid-turn
    // and moves the id from null to a real one. That is not a switch, and clearing
    // there would take the panel off the turn that is still on screen.
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });

    act(() => {
      receive("conversation_created", { conversation_id: "c-new" });
    });

    expect(result.current.pendingApproval).not.toBeNull();
  });

  it("draws what the continuation did, not just what it answered", async () => {
    // The whole second half of a turn used to be invisible. A continuation runs
    // inside the resume request, so its `tool_call` frames go to that response and
    // never to this socket: approving a command showed the approved step finishing
    // and nothing else, then an answer that accounted for work nobody had seen.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({
            run_id: "r-9",
            output: "Six sheets.",
            status: "completed",
            steps: [
              // The decided call comes back with the segment on some providers.
              // Its step is already on screen in the turn that parked, so drawing
              // it again would show one command twice.
              { tool_call_id: "tc-1", tool_name: "execute", args: {}, result: "ok" },
              {
                tool_call_id: "tc-2",
                tool_name: "execute",
                args: { command: "python parse.py" },
                result: "6 sheets",
              },
            ],
            parked: [],
          })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "execute", args: {} });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const continuation = useChatStore.getState().messages.at(-1);
    expect(continuation?.parts?.map((part) => part.toolCall?.id ?? part.type)).toEqual([
      "tc-2",
      "text",
    ]);
    expect(continuation?.parts?.[0]?.toolCall).toMatchObject({
      name: "execute",
      args: { command: "python parse.py" },
      result: "6 sheets",
      status: "completed",
    });
    expect(continuation?.content).toBe("Six sheets.");
  });

  it("puts the continuation in the same turn as the message that parked", async () => {
    // One run, one turn. The segments are separate messages - each is written as
    // it happens rather than folded back into the one before it - so the run id is
    // what tells the list they are one answer and not three agents.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "Six sheets.", status: "completed" })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const assistants = useChatStore
      .getState()
      .messages.filter((message) => message.role === "assistant");
    expect(assistants.map((message) => message.runId)).toEqual(["r-9", "r-9"]);
  });

  it("shows what the approved call returned, on the step that was approved", async () => {
    // The one call somebody deliberately reviewed used to be the one that opened
    // onto nothing: it was made by the execution that parked, so the resume
    // produces only its return and there is no step to hang it on but this one.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({
            run_id: "r-9",
            output: "Six sheets.",
            status: "completed",
            settled: [{ tool_call_id: "tc-1", result: "6 sheets" }],
          })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "execute", args: {} });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const approved = useChatStore
      .getState()
      .messages.flatMap((message) => message.parts ?? [])
      .find((part) => part.toolCall?.id === "tc-1");
    expect(approved?.toolCall).toMatchObject({ status: "completed", result: "6 sheets" });
  });

  it("draws the step the continuation parked on, and decides against that step", async () => {
    // The sequence in the report: approve, see nothing happen, get asked to approve
    // again. The second gated call had no step anywhere, and the panel still pointed
    // at the first turn - so the decision after it was written back onto a tool call
    // that message does not contain.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({
            run_id: "r-9",
            output: "",
            status: "awaiting_approval",
            steps: [
              {
                tool_call_id: "tc-2",
                tool_name: "execute",
                args: { command: "python parse.py" },
                result: null,
              },
            ],
            parked: [
              {
                id: "ar-2",
                tool_call_id: "tc-2",
                tool_name: "execute",
                tool_args: { command: "python parse.py" },
              },
            ],
          })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_call", { tool_call_id: "tc-1", tool_name: "execute", args: {} });
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "approve" }]);
    });

    const continuation = useChatStore.getState().messages.at(-1);
    const step = continuation?.parts?.find((part) => part.toolCall?.id === "tc-2");
    // `awaiting_approval`, not a spinner: it produces no result until somebody
    // decides, which is what the panel below is asking.
    expect(step?.toolCall?.status).toBe("awaiting_approval");
    expect(result.current.pendingApproval?.messageId).toBe(continuation?.id);
  });

  it("adds no continuation message when the resume produced nothing", async () => {
    // A resume into a refusal: nothing called, nothing said. A blank assistant
    // message there reads as the agent answering with silence.
    post.mockImplementation((url: string) =>
      url.endsWith("/resume")
        ? Promise.resolve({ run_id: "r-9", output: "", status: "completed", steps: [], parked: [] })
        : Promise.resolve({}),
    );
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("model_request_start", {});
    receive("tool_approval_required", {
      run_id: "r-9",
      action_requests: [{ id: "ar-1", tool_call_id: "tc-1", tool_name: "execute", args: {} }],
      review_configs: [],
    });
    receive("complete", {});
    const before = useChatStore.getState().messages.length;

    await act(async () => {
      await result.current.sendResumeDecisions([{ type: "reject" }]);
    });

    expect(useChatStore.getState().messages).toHaveLength(before);
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

  it("carries the per-turn model override, and only when it is set", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.sendMessage("first"));
    expect(frame(0)).not.toHaveProperty("model_profile_id");

    act(() => result.current.setModelProfile("p-1"));
    receive("complete", {});
    act(() => result.current.sendMessage("second"));

    expect(frame(1)).toMatchObject({ model_profile_id: "p-1" });
  });

  it("carries the approval mode, and only when it is not the agent's", () => {
    // A client that never touched the control sends nothing, and the server
    // follows the spec - which is the behaviour that existed before it (#925).
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => result.current.sendMessage("first"));
    expect(frame(0)).not.toHaveProperty("approval_mode");

    act(() => result.current.setApprovalMode("ask_all"));
    receive("complete", {});
    act(() => result.current.sendMessage("second"));

    expect(frame(1)).toMatchObject({ approval_mode: "ask_all" });
  });

  it("stops carrying it when the mode goes back to the agent's", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    act(() => result.current.setApprovalMode("approve_all"));
    act(() => result.current.sendMessage("first"));
    expect(frame(0)).toMatchObject({ approval_mode: "approve_all" });

    act(() => result.current.setApprovalMode("follow_agent"));
    receive("complete", {});
    act(() => result.current.sendMessage("second"));

    expect(frame(1)).not.toHaveProperty("approval_mode");
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

describe("what the person cannot reach", () => {
  const NOTION = {
    catalog_key: "notion",
    name: "Notion",
    gap: "not_connected",
    url: "http://localhost:3000/mcp-servers?connect=notion",
  };

  it("holds the turn's unavailable personal services for the card", () => {
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("personal_services_unavailable", { services: [NOTION] });

    expect(result.current.personalGaps).toEqual([NOTION]);
  });

  it("keeps them up past the end of the turn", () => {
    // The card belongs beside the answer that says the agent could not reach
    // them, and that answer is on screen after `complete`.
    const { result } = renderHook(() => useChat(), { wrapper });

    receive("personal_services_unavailable", { services: [NOTION] });
    receive("complete", {});

    expect(result.current.personalGaps).toEqual([NOTION]);
  });

  it("drops them when the next question is sent", () => {
    const { result } = renderHook(() => useChat(), { wrapper });
    receive("personal_services_unavailable", { services: [NOTION] });

    act(() => result.current.sendMessage("try again"));

    expect(result.current.personalGaps).toEqual([]);
  });
});
