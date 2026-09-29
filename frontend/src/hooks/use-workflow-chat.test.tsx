import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";

import { useWorkflowChat } from "./use-workflow-chat";

/** The browser's WebSocket, as far as the hook uses it. */
class FakeSocket {
  static opened: FakeSocket[] = [];
  sent: unknown[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(
    public url: string,
    public protocols?: string[],
  ) {
    FakeSocket.opened.push(this);
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.closed = true;
  }

  frame(data: unknown) {
    act(() => this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) })));
  }
}

const WORKFLOW = { id: "wf-1", name: "Lead triage" };

function answer() {
  const message = useChatStore.getState().messages.at(-1);
  return { message, card: message?.parts?.[0]?.workflowRun };
}

beforeEach(() => {
  FakeSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  useAuthStore.setState({ accessToken: "t-1" });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
});

afterEach(() => vi.unstubAllGlobals());

describe("useWorkflowChat", () => {
  it("opens a conversation for a first message and follows the run to its answer", async () => {
    const createConversation = vi.fn().mockResolvedValue({ id: "c-1" });
    const onConversationCreated = vi.fn();
    const { result } = renderHook(() =>
      useWorkflowChat({ createConversation, onConversationCreated }),
    );

    await act(() => result.current.send(WORKFLOW, "Score today's leads"));

    expect(createConversation).toHaveBeenCalledWith("Score today's leads");
    expect(onConversationCreated).toHaveBeenCalled();
    expect(useConversationStore.getState().currentConversationId).toBe("c-1");
    const [socket] = FakeSocket.opened;
    expect(socket?.url).toBe("ws://localhost:8000/api/v1/ws/workflow-runs?organization_id=org-1");
    expect(socket?.protocols).toEqual(["access_token.t-1", "workflow"]);
    const [question] = useChatStore.getState().messages;
    expect(question).toMatchObject({ role: "user", content: "Score today's leads" });
    expect(answer().card).toMatchObject({ workflowName: "Lead triage", status: "queued" });

    act(() => socket?.onopen?.());
    expect(socket?.sent).toEqual([
      {
        type: "start",
        workflow_id: "wf-1",
        conversation_id: "c-1",
        message: "Score today's leads",
      },
    ]);

    socket?.frame({ type: "run", run: { id: "r-1", status: "running" } });
    socket?.frame({ type: "event" });
    expect(answer().card).toMatchObject({ runId: "r-1", status: "running" });
    expect(answer().message?.isStreaming).toBe(true);

    socket?.frame({
      type: "run",
      run: { id: "r-1", status: "succeeded", output: { text: "Three are hot." }, error: null },
    });
    const { message, card } = answer();
    expect(card).toMatchObject({ status: "succeeded", error: null });
    expect(message?.content).toBe("Three are hot.");
    expect(message?.parts?.[1]).toMatchObject({ type: "text", content: "Three are hot." });
    expect(message?.isStreaming).toBe(false);
    expect(socket?.closed).toBe(true);
  });

  it("writes into the conversation already open, and says why a run was refused", async () => {
    useConversationStore.getState().setCurrentConversationId("c-open");
    useOrgStore.setState({ activeOrgId: null });
    useAuthStore.setState({ accessToken: null });
    const createConversation = vi.fn();
    const { result } = renderHook(() => useWorkflowChat({ createConversation }));

    await act(() => result.current.send(WORKFLOW, "Go"));

    expect(createConversation).not.toHaveBeenCalled();
    const [socket] = FakeSocket.opened;
    expect(socket?.url).toBe("ws://localhost:8000/api/v1/ws/workflow-runs");
    expect(socket?.protocols).toBeUndefined();
    socket?.frame({ type: "error", code: "NOT_FOUND", message: "Workflow not found" });
    expect(answer().card).toMatchObject({ status: "failed", error: "Workflow not found" });
    // A close after the refusal changes nothing it already said.
    act(() => socket?.onclose?.());
    expect(answer().card?.status).toBe("failed");
  });

  it("stops following a run whose socket went away, and leaves the card as it was", async () => {
    useConversationStore.getState().setCurrentConversationId("c-open");
    const { result } = renderHook(() => useWorkflowChat({ createConversation: vi.fn() }));
    await act(() => result.current.send(WORKFLOW, "Go"));
    const [socket] = FakeSocket.opened;
    socket?.frame({ type: "run", run: { id: "r-2", status: "running" } });

    act(() => socket?.onclose?.());

    expect(answer().card).toMatchObject({ runId: "r-2", status: "running" });
    expect(answer().message?.isStreaming).toBe(false);
  });

  it("sends nothing when the conversation could not be opened", async () => {
    const { result } = renderHook(() =>
      useWorkflowChat({ createConversation: vi.fn().mockResolvedValue(null) }),
    );
    await act(() => result.current.send(WORKFLOW, "Go"));
    expect(FakeSocket.opened).toEqual([]);
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("closes what it still has open when the chat goes away", async () => {
    useConversationStore.getState().setCurrentConversationId("c-open");
    const { result, unmount } = renderHook(() => useWorkflowChat({ createConversation: vi.fn() }));
    await act(() => result.current.send(WORKFLOW, "Go"));
    unmount();
    expect(FakeSocket.opened[0]?.closed).toBe(true);
  });

  it("ends the run with no words when it answered none", async () => {
    useConversationStore.getState().setCurrentConversationId("c-open");
    const { result } = renderHook(() => useWorkflowChat({ createConversation: vi.fn() }));
    await act(() => result.current.send(WORKFLOW, "Go"));
    FakeSocket.opened[0]?.frame({
      type: "run",
      run: { id: "r-3", status: "failed", output: null, error: { message: "Step 2 failed" } },
    });
    const { message, card } = answer();
    expect(card).toMatchObject({ status: "failed", error: "Step 2 failed" });
    expect(message?.parts).toHaveLength(1);
  });
});
