import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useChat } from "./use-chat";
import { qk } from "@/lib/query-keys";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useOrgStore,
  useWorkingStore,
} from "@/stores";
import { useChatControlsStore } from "@/stores/chat-controls-store";
import type { ChatMessage } from "@/types/chat";
import type { ParkedSecretRequest, ResumedRun } from "@/types/runs";

const { get, post, sent, socket } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  sent: vi.fn(),
  socket: { isConnected: true },
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ApiError: (await importOriginal<typeof import("@/lib/api-client")>()).ApiError,
  apiClient: { get, post },
}));
vi.mock("./use-websocket", () => ({
  useWebSocket: () => ({
    isConnected: socket.isConnected,
    connect: vi.fn(),
    disconnect: vi.fn(),
    reopen: vi.fn(),
    sendMessage: sent,
  }),
}));
vi.mock("@/lib/offline/device-cache", () => ({
  keepOutbox: vi.fn(async () => {}),
  keptOutbox: vi.fn(async () => []),
  readThrough: (_key: string, fetch: () => Promise<unknown>) => fetch(),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const requested: ParkedSecretRequest = {
  id: "secret-request-1",
  run_id: "run-1",
  tool_call_id: "secret-call-1",
  secret_name: "deployment_key",
  kind: "api_key",
  what_for: "Publish the approved preview.",
  status: "pending",
};
const completed: ResumedRun = {
  run_id: "run-1",
  status: "completed",
  output: "The old scope's continuation.",
  continues_in_chat: true,
  settled: [{ tool_call_id: requested.tool_call_id, result: "Stored securely." }],
  cost_usd: "0.01",
  cost_is_partial: false,
  input_tokens: 5,
  output_tokens: 5,
};
const clients: QueryClient[] = [];

function person(id: string) {
  return { id, email: `${id}@example.test`, is_active: true, created_at: "2026-11-14T08:00:00Z" };
}

function secretTurn(): ChatMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "",
    timestamp: new Date("2026-11-14T08:00:00Z"),
    conversationId: "conversation-1",
    runId: requested.run_id,
    runWaitingFor: "answer",
    toolCalls: [
      {
        id: requested.tool_call_id,
        name: "request_secret",
        args: { secret_name: requested.secret_name },
        status: "awaiting_answer",
      },
    ],
  };
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  });
  clients.push(client);
  client.setQueryData(qk.organizations.list(), [
    { id: "org-a", chat_may_waive_approvals: false },
    { id: "org-b", chat_may_waive_approvals: false },
  ]);
  for (const id of ["org-a", "org-b"]) {
    client.setQueryData(qk.organizations.permissions(id), {
      organization_id: id,
      role: "member",
      is_app_admin: false,
      permissions: [],
    });
  }
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function readDefault(path: string): Promise<unknown> {
  if (path === "/runs/run-1/secret-requests") {
    return useAuthStore.getState().user?.id === "owner-a" &&
      useOrgStore.getState().activeOrgId === "org-a" &&
      useConversationStore.getState().currentConversationId === "conversation-1"
      ? [requested]
      : [];
  }
  if (path === "/runs/run-1/questions") return [];
  if (path === "/runs/run-1/can-stop") return false;
  if (/^\/conversations\/conversation-[12]\/messages\?skip=0&limit=1$/.test(path)) {
    return { cost: null };
  }
  throw new Error(`Unexpected GET ${path}`);
}

type ContextChange = "conversation" | "organization" | "account";
const completionTransitions = (["fulfil", "decline"] as const).flatMap((action) =>
  (["conversation", "organization", "account", "unmount"] as const).map((kind) => ({
    action,
    kind,
  })),
);

function changeContext(kind: ContextChange) {
  if (kind === "conversation") {
    useConversationStore.getState().setCurrentConversationId("conversation-2");
  } else if (kind === "organization") {
    useOrgStore.setState({ activeOrgId: "org-b" });
  } else {
    useAuthStore.setState({ user: person("owner-b") });
  }
}

beforeEach(() => {
  vi.resetAllMocks();
  socket.isConnected = true;
  useChatControlsStore.setState({ byScope: {} });
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useAuthStore.setState({ accessToken: "test-token", user: person("owner-a") });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useWorkingStore.getState().reset();
  useConversationStore.getState().reset();
  useConversationStore.getState().setCurrentConversationId("conversation-1");
  useChatStore.getState().clearMessages();
  useChatStore.getState().rereadMessages([secretTurn()], {
    conversationId: "conversation-1",
    selectionVersion: useConversationStore.getState().selectionVersion,
    accountId: "owner-a",
    tenantId: "org-a",
  });
  get.mockImplementation(readDefault);
  post.mockResolvedValue(completed);
});

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

describe("parked secret-request context", () => {
  it("restores only the pending metadata belonging to the person asked", async () => {
    get.mockImplementation(async (path: string) =>
      path === "/runs/run-1/secret-requests"
        ? [{ ...requested, id: "already-fulfilled", status: "fulfilled" }, requested]
        : readDefault(path),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });

    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    expect(get.mock.calls.filter(([path]) => path.endsWith("/secret-requests"))).toEqual([
      ["/runs/run-1/secret-requests"],
    ]);
    expect(post).not.toHaveBeenCalled();
  });

  it.each(["conversation", "organization", "account"] as const)(
    "removes the old actionable card when the %s changes",
    async (kind) => {
      const { wrapper } = setup();
      const { result } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

      act(() => changeContext(kind));

      await waitFor(() => expect(result.current.pendingSecretRequests).toBeNull());
      await act(async () => {
        await result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression");
        await result.current.declineSecretRequest(requested.id);
      });
      expect(post).not.toHaveBeenCalled();
    },
  );

  it.each(["conversation", "organization", "account", "visit-again"] as const)(
    "ignores a delayed metadata read after a %s transition",
    async (kind) => {
      const pending = deferred<ParkedSecretRequest[]>();
      let reads = 0;
      get.mockImplementation((path: string) => {
        if (path === "/runs/run-1/secret-requests") {
          reads += 1;
          return reads === 1 ? pending.promise : Promise.resolve([]);
        }
        return readDefault(path);
      });
      const { wrapper } = setup();
      const { result } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(reads).toBe(1));

      if (kind === "visit-again") {
        act(() => useConversationStore.getState().setCurrentConversationId("conversation-2"));
        act(() => useConversationStore.getState().setCurrentConversationId("conversation-1"));
      } else {
        act(() => changeContext(kind));
      }
      await act(async () => pending.resolve([requested]));

      expect(result.current.pendingSecretRequests).toBeNull();
      expect(toast.error).not.toHaveBeenCalled();
    },
  );

  it("restores the pending card after Strict Mode replays the initial effects", async () => {
    const { wrapper: Wrapper } = setup();
    const { result } = renderHook(() => useChat(), {
      wrapper: ({ children }) => (
        <StrictMode>
          <Wrapper>{children}</Wrapper>
        </StrictMode>
      ),
    });

    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
    await act(async () => result.current.declineSecretRequest(requested.id));

    expect(post).toHaveBeenCalledExactlyOnceWith(
      "/runs/run-1/secret-requests/secret-request-1/decline",
      {},
    );
    expect(result.current.pendingSecretRequests).toEqual([]);
  });

  it("retains the card across an access-token refresh for the same person and organization", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    act(() => useAuthStore.setState({ accessToken: "refreshed-test-token" }));

    expect(result.current.pendingSecretRequests).toEqual([requested]);
    await act(async () => result.current.declineSecretRequest(requested.id));
    expect(post).toHaveBeenCalledTimes(1);
  });

  it.each(["conversation", "organization", "account", "visit-again"] as const)(
    "rejects retained handlers in the same tick as a %s transition",
    async (kind) => {
      const { wrapper } = setup();
      const { result } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
      const { submitSecretRequest, declineSecretRequest } = result.current;

      await act(async () => {
        if (kind === "visit-again") {
          useConversationStore.getState().setCurrentConversationId("conversation-2");
          useConversationStore.getState().setCurrentConversationId("conversation-1");
        } else {
          changeContext(kind);
        }
        await submitSecretRequest(requested.id, "dummy-secret-for-regression");
        await declineSecretRequest(requested.id);
      });

      expect(post).not.toHaveBeenCalled();
    },
  );

  it("retries a failed metadata read on reconnect without showing a stale card", async () => {
    let reads = 0;
    get.mockImplementation((path: string) => {
      if (path === "/runs/run-1/secret-requests" && ++reads === 1) {
        return Promise.reject(new Error("Temporarily unavailable"));
      }
      return readDefault(path);
    });
    const { wrapper } = setup();
    const { result, rerender } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(reads).toBe(1));
    await act(async () => {});
    expect(result.current.pendingSecretRequests).toBeNull();
    expect(toast.error).not.toHaveBeenCalled();

    socket.isConnected = false;
    rerender();
    socket.isConnected = true;
    rerender();

    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
    expect(reads).toBe(2);
  });

  it.each(completionTransitions)(
    "does not draw a late $action into a changed $kind",
    async ({ action, kind }) => {
      const pending = deferred<ResumedRun>();
      post.mockReturnValueOnce(pending.promise);
      const { wrapper } = setup();
      const { result, unmount } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
      let submission!: Promise<void>;
      act(() => {
        submission =
          action === "fulfil"
            ? result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression")
            : result.current.declineSecretRequest(requested.id);
      });
      expect(post).toHaveBeenCalledExactlyOnceWith(
        `/runs/run-1/secret-requests/secret-request-1/${action}`,
        action === "fulfil" ? { value: "dummy-secret-for-regression" } : {},
      );

      if (kind === "unmount") unmount();
      else act(() => changeContext(kind));
      if (kind !== "unmount") expect(result.current.isProcessing).toBe(false);
      const before = JSON.stringify(useChatStore.getState().messages);
      await act(async () => {
        pending.resolve(completed);
        await submission;
      });

      expect(JSON.stringify(useChatStore.getState().messages)).toBe(before);
      expect(toast.info).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
      expect(JSON.stringify(sent.mock.calls)).not.toContain("dummy-secret-for-regression");
    },
  );

  it.each(completionTransitions)(
    "does not announce a late $action error after a changed $kind",
    async ({ action, kind }) => {
      const pending = deferred<ResumedRun>();
      post.mockReturnValueOnce(pending.promise);
      const { wrapper } = setup();
      const { result, unmount } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
      let submission!: Promise<void>;
      act(() => {
        submission =
          action === "fulfil"
            ? result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression")
            : result.current.declineSecretRequest(requested.id);
      });
      if (kind === "unmount") unmount();
      else act(() => changeContext(kind));
      const before = JSON.stringify(useChatStore.getState().messages);

      await act(async () => {
        pending.reject(new Error("The previous context is offline."));
        await submission;
      });

      expect(JSON.stringify(useChatStore.getState().messages)).toBe(before);
      expect(toast.error).not.toHaveBeenCalled();
      expect(toast.info).not.toHaveBeenCalled();
    },
  );
});

describe("parked secret-request decisions", () => {
  it("ignores an unknown request id without sending or consuming the pending card", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    await act(async () => {
      await result.current.submitSecretRequest("not-offered", "dummy-secret-for-regression");
      await result.current.declineSecretRequest("not-offered");
    });

    expect(post).not.toHaveBeenCalled();
    expect(result.current.pendingSecretRequests).toEqual([requested]);
  });

  it.each([true, false])(
    "fulfils only over HTTP and draws the accepted continuation (chat notice: %s)",
    async (continuesInChat) => {
      const response: ResumedRun = {
        ...completed,
        continues_in_chat: continuesInChat,
        settled: continuesInChat ? completed.settled : undefined,
      };
      post.mockResolvedValue(response);
      const { client, wrapper } = setup();
      const { result } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
      const value = "dummy-secret-for-regression";

      await act(async () => result.current.submitSecretRequest(requested.id, value));

      expect(post).toHaveBeenCalledExactlyOnceWith(
        "/runs/run-1/secret-requests/secret-request-1/fulfil",
        { value },
      );
      expect(result.current.pendingSecretRequests).toEqual([]);
      expect(result.current.isProcessing).toBe(false);
      const messages = useChatStore.getState().messages;
      expect(messages.find((message) => message.id === "message-1")).toMatchObject({
        runWaitingFor: undefined,
        toolCalls: [
          {
            id: requested.tool_call_id,
            status: "completed",
            result: continuesInChat ? "Stored securely." : undefined,
          },
        ],
      });
      expect(messages.filter((message) => message.content === completed.output)).toHaveLength(1);
      expect(toast.info).toHaveBeenCalledTimes(continuesInChat ? 1 : 0);
      expect(toast.error).not.toHaveBeenCalled();
      expect(
        JSON.stringify({
          messages,
          pending: result.current.pendingSecretRequests,
          socket: sent.mock.calls,
          cache: client
            .getQueryCache()
            .getAll()
            .map((query) => query.state.data),
        }),
      ).not.toContain(value);
    },
  );

  it("keeps a refused fulfilment answerable and permits an explicit retry", async () => {
    post.mockRejectedValueOnce(new Error("Could not seal the value"));
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    await act(async () =>
      result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression"),
    );

    expect(result.current.pendingSecretRequests).toEqual([requested]);
    expect(result.current.isProcessing).toBe(false);
    expect(useChatStore.getState().messages[0]?.toolCalls?.[0]?.status).toBe("awaiting_answer");
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.info).not.toHaveBeenCalled();

    await act(async () =>
      result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression"),
    );
    expect(post).toHaveBeenCalledTimes(2);
    expect(result.current.pendingSecretRequests).toEqual([]);
    expect(useChatStore.getState().messages[0]?.toolCalls?.[0]?.status).toBe("completed");
  });

  it.each(["fulfil", "decline"] as const)(
    "allows only one in-flight decision while %s is pending",
    async (action) => {
      const pending = deferred<ResumedRun>();
      post.mockReturnValueOnce(pending.promise);
      const { wrapper } = setup();
      const { result } = renderHook(() => useChat(), { wrapper });
      await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));
      let first!: Promise<void>;

      await act(async () => {
        first =
          action === "fulfil"
            ? result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression")
            : result.current.declineSecretRequest(requested.id);
        await result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression");
        await result.current.declineSecretRequest(requested.id);
      });
      expect(post).toHaveBeenCalledTimes(1);
      expect(result.current.isProcessing).toBe(action === "fulfil");
      await act(async () => {
        pending.resolve(completed);
        await first;
      });
      expect(result.current.pendingSecretRequests).toEqual([]);
      expect(result.current.isProcessing).toBe(false);
    },
  );

  it("restores the remaining pending secret after the first fulfilment parks the run again", async () => {
    const second = {
      ...requested,
      id: "secret-request-2",
      tool_call_id: "secret-call-2",
      secret_name: "registry_key",
    };
    const turn = secretTurn();
    useChatStore.getState().updateMessage(turn.id, (message) => ({
      ...message,
      toolCalls: [
        ...(message.toolCalls ?? []),
        {
          id: second.tool_call_id,
          name: "request_secret",
          args: { secret_name: second.secret_name },
          status: "awaiting_answer",
        },
      ],
    }));
    let firstAccepted = false;
    get.mockImplementation((path: string) =>
      path === "/runs/run-1/secret-requests"
        ? Promise.resolve([
            { ...requested, status: firstAccepted ? "fulfilled" : "pending" },
            second,
          ])
        : readDefault(path),
    );
    post.mockImplementation(async () => {
      firstAccepted = true;
      return { ...completed, status: "awaiting_answer", output: "", continues_in_chat: false };
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested, second]));

    await act(async () =>
      result.current.submitSecretRequest(requested.id, "dummy-secret-for-regression"),
    );

    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([second]));
    expect(useChatStore.getState().messages[0]?.toolCalls).toEqual([
      expect.objectContaining({ id: requested.tool_call_id, status: "completed" }),
      expect.objectContaining({ id: second.tool_call_id, status: "awaiting_answer" }),
    ]);
    expect(result.current.isProcessing).toBe(false);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("declines the request, ends its waiting marker, and settles other open calls without resuming", async () => {
    useChatStore.getState().updateMessage("message-1", (message) => ({
      ...message,
      toolCalls: [
        ...(message.toolCalls ?? []),
        { id: "other-call", name: "build", args: {}, status: "running" },
      ],
    }));
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    await act(async () => result.current.declineSecretRequest(requested.id));

    expect(post).toHaveBeenCalledExactlyOnceWith(
      "/runs/run-1/secret-requests/secret-request-1/decline",
      {},
    );
    expect(result.current.pendingSecretRequests).toEqual([]);
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0]).toMatchObject({
      runWaitingFor: undefined,
      toolCalls: [
        {
          id: requested.tool_call_id,
          status: "completed",
          result: "You declined to provide this secret",
        },
        { id: "other-call", status: "unfinished" },
      ],
    });
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("retains a refused decline for an explicit retry", async () => {
    post.mockRejectedValueOnce(new Error("Could not decline the request"));
    const { wrapper } = setup();
    const { result } = renderHook(() => useChat(), { wrapper });
    await waitFor(() => expect(result.current.pendingSecretRequests).toEqual([requested]));

    await act(async () => result.current.declineSecretRequest(requested.id));
    expect(result.current.pendingSecretRequests).toEqual([requested]);
    expect(useChatStore.getState().messages[0]?.toolCalls?.[0]?.status).toBe("awaiting_answer");
    expect(toast.error).toHaveBeenCalledTimes(1);

    await act(async () => result.current.declineSecretRequest(requested.id));
    expect(post).toHaveBeenCalledTimes(2);
    expect(result.current.pendingSecretRequests).toEqual([]);
  });
});
