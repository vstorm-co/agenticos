import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  useAgentMessageRecipients,
  useAgentMessageThread,
  useAgentMessageThreads,
  useAgentMessages,
  useMarkAgentMessageThreadRead,
  useReactToAgentMessage,
  useSendAgentMessage,
} from "./use-agent-messages";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  AgentMessageRead,
  AgentMessageSend,
  AgentMessageThreadRead,
} from "@/types/agent-messages";
import messages from "../../messages/en.json";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const thread: AgentMessageThreadRead = {
  id: "thread-1",
  agent_a: { id: "agent-a", slug: "planner", name: "Planner" },
  agent_b: { id: "agent-b", slug: "reviewer", name: "Reviewer" },
  last_message_at: null,
  last_message: null,
  unread: true,
  created_at: "2026-11-14T08:00:00Z",
  updated_at: "2026-11-14T08:00:00Z",
};
const message: AgentMessageRead = {
  id: "message-1",
  thread_id: thread.id,
  sender_agent_id: thread.agent_a.id,
  sender_agent_slug: thread.agent_a.slug,
  sender_user_id: "person-1",
  body: "Please review this plan.",
  reply_to_message_id: null,
  reactions: [],
  attachments: [],
  created_at: thread.created_at,
  updated_at: thread.updated_at,
};
const input: AgentMessageSend = {
  sender_agent_id: thread.agent_a.id,
  recipient: thread.agent_b.slug,
  body: message.body,
};
const emptyPage = { items: [], total: 0 };
const clients: QueryClient[] = [];

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  clients.push(client);
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function seedLists(client: QueryClient) {
  client.setQueryData(qk.agentMessages.list(0, 50), emptyPage);
  client.setQueryData(qk.agentMessages.list(50, 50), emptyPage);
  client.setQueryData(qk.agentMessages.messages(thread.id), emptyPage);
  client.setQueryData(qk.agentMessages.messages("other-thread"), emptyPage);
  client.setQueryData(qk.agentMessages.recipients(), emptyPage);
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

describe("agent-message reads", () => {
  it("exposes pending defaults, then the four permission-scoped results and totals", async () => {
    const threads = deferred<unknown>();
    const detail = deferred<unknown>();
    const history = deferred<unknown>();
    const recipients = deferred<unknown>();
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (path === "/agent-messages") return threads.promise;
      if (path === "/agent-messages/thread-1") return detail.promise;
      if (path === "/agent-messages/thread-1/messages") return history.promise;
      if (path === "/agent-messages/recipients") return recipients.promise;
      throw new Error(`Unexpected request: ${path}`);
    });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({
        threads: useAgentMessageThreads(20, 10),
        detail: useAgentMessageThread(thread.id),
        history: useAgentMessages(thread.id, 30, 15),
        recipients: useAgentMessageRecipients(40, 20),
      }),
      { wrapper },
    );

    expect(result.current.threads).toMatchObject({
      threads: [],
      total: 0,
      isLoading: true,
      error: null,
    });
    expect(result.current.detail).toMatchObject({ thread: null, isLoading: true, error: null });
    expect(result.current.history).toMatchObject({
      messages: [],
      total: 0,
      isLoading: true,
      error: null,
    });
    expect(result.current.recipients).toMatchObject({
      recipients: [],
      total: 0,
      isLoading: true,
      error: null,
    });

    await act(async () => {
      threads.resolve({ items: [thread], total: 71 });
      detail.resolve(thread);
      history.resolve({ items: [message], total: 92 });
      recipients.resolve({ items: [thread.agent_b], total: 133 });
    });

    await waitFor(() => expect(result.current.recipients.isLoading).toBe(false));
    expect(result.current.threads).toMatchObject({
      threads: [thread],
      total: 71,
      isLoading: false,
      error: null,
    });
    expect(result.current.detail).toMatchObject({ thread, isLoading: false, error: null });
    expect(result.current.history).toMatchObject({
      messages: [message],
      total: 92,
      isLoading: false,
      error: null,
    });
    expect(result.current.recipients).toMatchObject({
      recipients: [thread.agent_b],
      total: 133,
      error: null,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages", {
      params: { skip: "20", limit: "10" },
    });
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages/thread-1");
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages/thread-1/messages", {
      params: { skip: "30", limit: "15" },
    });
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages/recipients", {
      params: { skip: "40", limit: "20" },
    });
  });

  it.each([
    {
      name: "thread list",
      useRead: () => useAgentMessageThreads(),
      response: { items: [thread], total: 1 },
    },
    { name: "thread detail", useRead: () => useAgentMessageThread(thread.id), response: thread },
    {
      name: "message history",
      useRead: () => useAgentMessages(thread.id),
      response: { items: [message], total: 1 },
    },
    {
      name: "recipients",
      useRead: () => useAgentMessageRecipients(),
      response: { items: [thread.agent_b], total: 1 },
    },
  ])(
    "surfaces the $name refusal and clears it after an explicit successful retry",
    async ({ useRead, response }) => {
      const refusal = new ApiError(403, "You may not run this agent.");
      vi.mocked(apiClient.get).mockRejectedValueOnce(refusal);
      const { wrapper } = setup();
      const { result } = renderHook(() => useRead(), { wrapper });

      await waitFor(() => expect(result.current.error).toBe(refusal.message));
      expect(result.current.isLoading).toBe(false);
      expect(apiClient.get).toHaveBeenCalledTimes(1);
      vi.mocked(apiClient.get).mockResolvedValueOnce(response);

      await act(async () => {
        await result.current.refetch();
      });

      await waitFor(() => expect(result.current.error).toBeNull());
      expect(apiClient.get).toHaveBeenCalledTimes(2);
      expect(toast.success).not.toHaveBeenCalled();
    },
  );

  it("waits for an actual thread selection before reading its detail or messages", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path.endsWith("/messages") ? { items: [message], total: 1 } : thread,
    );
    const { wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => ({
        detail: useAgentMessageThread(id),
        history: useAgentMessages(id),
      }),
      { wrapper, initialProps: { id: null as string | null } },
    );

    expect(result.current.detail).toMatchObject({ thread: null, isLoading: false, error: null });
    expect(result.current.history).toMatchObject({
      messages: [],
      total: 0,
      isLoading: false,
      error: null,
    });
    expect(apiClient.get).not.toHaveBeenCalled();

    rerender({ id: thread.id });

    await waitFor(() => expect(result.current.detail.thread).toEqual(thread));
    await waitFor(() => expect(result.current.history.messages).toEqual([message]));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages/thread-1");
    expect(apiClient.get).toHaveBeenCalledWith("/agent-messages/thread-1/messages", {
      params: { skip: "0", limit: "50" },
    });
  });
});

describe("agent-message mutations", () => {
  it("refreshes every thread-list page and only the sent thread's messages after the server accepts a send", async () => {
    const accepted = deferred<AgentMessageRead>();
    vi.mocked(apiClient.post).mockReturnValueOnce(accepted.promise);
    const { client, wrapper } = setup();
    seedLists(client);
    const { result } = renderHook(useSendAgentMessage, { wrapper });

    act(() => result.current.send.mutate(input));

    await waitFor(() => expect(result.current.send.isPending).toBe(true));
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/agent-messages", input);
    expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(false);
    expect(toast.success).not.toHaveBeenCalled();

    await act(async () => accepted.resolve(message));

    await waitFor(() => expect(result.current.send.isSuccess).toBe(true));
    expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.agentMessages.list(50, 50))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.agentMessages.messages(thread.id))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.agentMessages.messages("other-thread"))?.isInvalidated).toBe(
      false,
    );
    expect(client.getQueryState(qk.agentMessages.recipients())?.isInvalidated).toBe(false);
    expect(toast.success).toHaveBeenCalledExactlyOnceWith(messages.agentMessages.sent);
  });

  it("preserves the sender's permission refusal without invalidating accepted-message caches", async () => {
    const refusal = new ApiError(403, "You must be able to run both agents.");
    vi.mocked(apiClient.post).mockRejectedValueOnce(refusal);
    const { client, wrapper } = setup();
    seedLists(client);
    const { result } = renderHook(useSendAgentMessage, { wrapper });

    await act(async () => {
      await expect(result.current.send.mutateAsync(input)).rejects.toBe(refusal);
    });

    expect(toast.error).toHaveBeenCalledExactlyOnceWith(refusal.message);
    expect(toast.success).not.toHaveBeenCalled();
    expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(false);
    expect(client.getQueryState(qk.agentMessages.messages(thread.id))?.isInvalidated).toBe(false);
  });

  it.each([undefined, "agent-a"])(
    "refreshes only the reacted thread when reacting as %s",
    async (asAgentId) => {
      const response = { reacted: true, reactions: [] };
      vi.mocked(apiClient.post).mockResolvedValueOnce(response);
      const { client, wrapper } = setup();
      seedLists(client);
      const { result } = renderHook(useReactToAgentMessage, { wrapper });

      await act(async () => {
        await expect(
          result.current.react.mutateAsync({
            threadId: thread.id,
            messageId: message.id,
            emoji: "👍",
            asAgentId,
          }),
        ).resolves.toBe(response);
      });

      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
        "/agent-messages/thread-1/messages/message-1/reactions",
        { emoji: "👍", as_agent_id: asAgentId ?? null },
      );
      expect(client.getQueryState(qk.agentMessages.messages(thread.id))?.isInvalidated).toBe(true);
      expect(client.getQueryState(qk.agentMessages.messages("other-thread"))?.isInvalidated).toBe(
        false,
      );
      expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(false);
    },
  );

  it("shows a refused reaction without claiming the cached message changed", async () => {
    const refusal = new ApiError(403, "This agent is not in the thread.");
    vi.mocked(apiClient.post).mockRejectedValueOnce(refusal);
    const { client, wrapper } = setup();
    seedLists(client);
    const { result } = renderHook(useReactToAgentMessage, { wrapper });

    await act(async () => {
      await expect(
        result.current.react.mutateAsync({
          threadId: thread.id,
          messageId: message.id,
          emoji: "👍",
          asAgentId: "outsider",
        }),
      ).rejects.toBe(refusal);
    });

    expect(toast.error).toHaveBeenCalledExactlyOnceWith(refusal.message);
    expect(client.getQueryState(qk.agentMessages.messages(thread.id))?.isInvalidated).toBe(false);
  });

  it("refreshes both unread-list pages only after the read watermark is persisted", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);
    const { client, wrapper } = setup();
    seedLists(client);
    const { result } = renderHook(useMarkAgentMessageThreadRead, { wrapper });

    await act(async () => {
      await expect(result.current.markRead.mutateAsync(thread.id)).resolves.toBeUndefined();
    });

    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/agent-messages/thread-1/read",
      undefined,
    );
    expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.agentMessages.list(50, 50))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.agentMessages.messages(thread.id))?.isInvalidated).toBe(false);
    expect(client.getQueryState(qk.agentMessages.recipients())?.isInvalidated).toBe(false);
  });

  it("leaves unread caches intact and returns a failed read-watermark request to the caller", async () => {
    const refusal = new ApiError(403, "You cannot read this thread.");
    vi.mocked(apiClient.post).mockRejectedValueOnce(refusal);
    const { client, wrapper } = setup();
    seedLists(client);
    const { result } = renderHook(useMarkAgentMessageThreadRead, { wrapper });

    await act(async () => {
      await expect(result.current.markRead.mutateAsync(thread.id)).rejects.toBe(refusal);
    });

    expect(client.getQueryState(qk.agentMessages.list(0, 50))?.isInvalidated).toBe(false);
    expect(client.getQueryState(qk.agentMessages.list(50, 50))?.isInvalidated).toBe(false);
    expect(toast.success).not.toHaveBeenCalled();
  });
});
