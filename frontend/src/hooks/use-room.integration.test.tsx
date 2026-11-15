import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { RoomMessageResult } from "@/types/room";
import { useCreateTeamRoom, useRoomActions, useRoomRequests, useRoomSync } from "./use-room";
import { useRoomDraft } from "./use-room-draft";
import { useRoomThread } from "./use-room-thread";
import { getRoomThread } from "@/lib/room-api";
import { resetTenantState } from "@/stores/session-reset";
import type { RoomThreadPage } from "@/types/room";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const user = (id = "me") => ({
  id,
  email: `${id}@example.com`,
  is_active: true,
  created_at: "2026-11-13T00:00:00Z",
});
const saved: RoomMessageResult = {
  message: {
    id: "saved-message",
    conversation_id: "room-a",
    content: "Hello",
    role: "user",
    created_at: "2026-11-13T00:00:00Z",
  },
  request: null,
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({ user: user() });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a" });
  useChatStore.setState({ messages: [], replyTo: null, roomDrafts: {} });
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/orgs" ? { items: [] } : { items: [], total: 0, can_post: true },
  );
  vi.mocked(apiClient.post).mockResolvedValue(saved);
});
afterEach(() => client.clear());

describe("posting to a room", () => {
  it("posts a human message and reply without inferring an agent", async () => {
    useChatStore.setState({ replyTo: { messageId: "parent", role: "user", excerpt: "Earlier" } });
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("  Hello  "));
    await act(async () => result.current.submit());
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/room-a/room-messages", {
      client_message_id: expect.any(String),
      content: "Hello",
      reply_to_message_id: "parent",
    });
    expect(result.current.content).toBe("");
    expect(useChatStore.getState().replyTo).toBeNull();
  });

  it("retries an uncertain acknowledgement with the same id, text, responder and reply", async () => {
    useChatStore.setState({ replyTo: { messageId: "parent", role: "user", excerpt: "Earlier" } });
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Network lost"));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.setContent("Please check");
      result.current.setAgentId("agent-a");
    });
    await act(async () => result.current.submit());
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    expect(result.current.retrying).toBe(true);
    expect(result.current.locked).toBe(true);
    expect(result.current.content).toBe("Please check");
    act(() =>
      useChatStore.setState({
        replyTo: { messageId: "another", role: "user", excerpt: "A new reply" },
      }),
    );
    await act(async () => result.current.submit());
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
    expect(first).toMatchObject({
      content: "Please check",
      agent_id: "agent-a",
      reply_to_message_id: "parent",
    });
    expect(result.current.content).toBe("");
    expect(result.current.agentId).toBeNull();
    expect(useChatStore.getState().replyTo?.messageId).toBe("another");
  });

  it("keeps an editable draft after a definite validation refusal", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new ApiError(422, "Reply no longer exists"));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("Hello"));
    await act(async () => result.current.submit());
    expect(result.current.content).toBe("Hello");
    expect(result.current.locked).toBe(false);
    expect(result.current.error).toBeTruthy();
  });

  it("retains an uncertain token when a later retry is refused after access changes", async () => {
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new TypeError("Acknowledgement lost"))
      .mockRejectedValueOnce(new ApiError(403, "Access changed"));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("Do this once"));
    await act(async () => result.current.submit());
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    await act(async () => result.current.submit());
    expect(result.current.locked).toBe(true);
    expect(result.current.retrying).toBe(true);
    await act(async () => result.current.submit());
    expect(vi.mocked(apiClient.post).mock.calls[2]![1]).toEqual(first);
  });

  it("admits only one in-flight click", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("Hello"));
    let posting!: Promise<void>;
    act(() => {
      posting = result.current.submit();
      void result.current.submit();
    });
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await act(async () => {
      pending.resolve(saved);
      await posting;
    });
    expect(result.current.content).toBe("");
  });

  it.each(["conversation", "account", "organization"] as const)(
    "ignores a late acknowledgement after the %s changes",
    async (boundary) => {
      const pending = deferred<RoomMessageResult>();
      vi.mocked(apiClient.post).mockReturnValue(pending.promise);
      const changed = vi.fn();
      const unsubscribe = onRoomChange(changed);
      const { result } = renderHook(() => useRoomActions("room-a"), { wrapper });
      const posting = result.current.post({ client_message_id: "stable-id", content: "Hello" });
      act(() => {
        if (boundary === "conversation")
          useConversationStore.setState({ currentConversationId: "room-b" });
        if (boundary === "account") useAuthStore.setState({ user: user("other") });
        if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-b" });
        useChatStore.setState({ replyTo: { messageId: "b-reply", role: "user", excerpt: "B" } });
      });
      client.setQueryData(qk.roomRequests.list("me", "org-a", "room-b"), { items: ["keep-b"] });
      pending.resolve(saved);
      await expect(posting).resolves.toBeNull();
      expect(changed).not.toHaveBeenCalled();
      expect(useChatStore.getState().replyTo?.messageId).toBe("b-reply");
      expect(client.getQueryData(qk.roomRequests.list("me", "org-a", "room-b"))).toEqual({
        items: ["keep-b"],
      });
      unsubscribe();
    },
  );

  it("drops a failed response after the form unmounts", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(() => useRoomActions("room-a"), { wrapper });
    const posting = result.current.post({ client_message_id: "one", content: "Hello" });
    unmount();
    pending.reject(new Error("old request"));
    await expect(posting).resolves.toBeNull();
  });

  it("does not start a request for a room that is no longer selected", async () => {
    const { result } = renderHook(() => useRoomActions("room-a"), { wrapper });
    act(() => useConversationStore.setState({ currentConversationId: "room-b" }));
    await expect(
      result.current.post({ client_message_id: "one", content: "Hello" }),
    ).resolves.toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("clears the selected reply without discarding the draft text", () => {
    useChatStore.setState({ replyTo: { messageId: "parent", role: "user", excerpt: "Earlier" } });
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("Keep this draft"));
    act(() => result.current.clearReply());
    expect(result.current.reply).toBeNull();
    expect(useChatStore.getState().replyTo).toBeNull();
    expect(result.current.content).toBe("Keep this draft");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not draw a refusal when the organization changes before the draft receives it", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setContent("The original draft"));
    let posting!: Promise<void>;
    act(() => {
      posting = result.current.submit();
    });

    await act(async () => {
      pending.reject(new ApiError(403, "Access changed"));
      // The transport's refusal is queued first; selection changes before the
      // outer draft continuation receives that refusal.
      queueMicrotask(() => useOrgStore.setState({ activeOrgId: "org-b" }));
      await posting;
    });

    expect(result.current.error).toBeNull();
    expect(result.current.content).toBe("");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
});

it("refreshes authoritative posting access on a matching room event only", async () => {
  let canPost = true;
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/orgs" ? { items: [] } : { items: [], total: 0, can_post: canPost },
  );
  const { result } = renderHook(() => useRoomRequests("room-a"), { wrapper });
  await waitFor(() => expect(result.current.data?.can_post).toBe(true));
  canPost = false;
  act(() =>
    announceRoomChange({ conversationId: "room-a", accountId: "other", organizationId: "org-a" }),
  );
  expect(result.current.data?.can_post).toBe(true);
  act(() =>
    announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" }),
  );
  await waitFor(() => expect(result.current.data?.can_post).toBe(false));
});

it("refreshes a human message while preserving an unsaved streaming answer", async () => {
  vi.useFakeTimers();
  const human = { id: "human", role: "user" as const, content: "Question", timestamp: new Date() };
  const live = {
    id: "live",
    role: "assistant" as const,
    content: "Still writing",
    timestamp: new Date(),
    isStreaming: true,
  };
  useChatStore.setState({ messages: [human, live] });
  const reread = vi.fn(async () => {
    useChatStore
      .getState()
      .rereadMessages([
        human,
        { id: "teammate", role: "user", content: "An update", timestamp: new Date() },
      ]);
  });
  const { unmount } = renderHook(() => useRoomSync("room-a", reread), { wrapper });
  try {
    act(() =>
      announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" }),
    );
    await act(async () => vi.advanceTimersByTimeAsync(150));
    expect(useChatStore.getState().messages).toEqual(expect.arrayContaining([live]));
    expect(useChatStore.getState().messages.map((message) => message.id)).toContain("teammate");
    expect(reread).toHaveBeenCalledWith("room-a");
  } finally {
    unmount();
    vi.useRealTimers();
  }
});

it.each([
  { conversationId: "room-b", accountId: "me", organizationId: "org-a" },
  { conversationId: "room-a", accountId: "other", organizationId: "org-a" },
  { conversationId: "room-a", accountId: "me", organizationId: "org-b" },
])("ignores a transcript event outside the selected identity: %j", async (event) => {
  vi.useFakeTimers();
  const reread = vi.fn(async () => {});
  const { unmount } = renderHook(() => useRoomSync("room-a", reread), { wrapper });
  try {
    act(() => announceRoomChange(event));
    await act(async () => vi.advanceTimersByTimeAsync(150));
    expect(reread).not.toHaveBeenCalled();
    act(() =>
      announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" }),
    );
    await act(async () => vi.advanceTimersByTimeAsync(150));
    expect(reread).toHaveBeenCalledExactlyOnceWith("room-a");
  } finally {
    unmount();
    vi.useRealTimers();
  }
});

it("creates an empty project room without invoking an agent", async () => {
  vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "new-room", project_id: "project-a" });
  const { result } = renderHook(() => useCreateTeamRoom(), { wrapper });
  await act(async () =>
    expect(result.current.create("project-a", "Our team")).resolves.toMatchObject({
      id: "new-room",
    }),
  );
  expect(apiClient.post).toHaveBeenCalledWith("/conversations", {
    project_id: "project-a",
    title: "Our team",
  });
});

describe("room creation readiness", () => {
  it.each(["account", "organization", "fallback"] as const)(
    "refuses a programmatic create while %s initialization is incomplete",
    async (pending) => {
      if (pending === "account") useAuthStore.setState({ user: null });
      else useOrgStore.setState({ activeOrgId: null });
      if (pending === "fallback") {
        client.setQueryDefaults(qk.organizations.list(), { staleTime: Infinity });
        client.setQueryData(qk.organizations.list(), [{ id: "org-a", is_personal: true }]);
      }
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const { result } = renderHook(() => useCreateTeamRoom(), { wrapper });
      expect(result.current.isReady).toBe(false);
      await act(async () =>
        expect(result.current.create("project-a", "Our team")).resolves.toBeNull(),
      );
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(invalidate).not.toHaveBeenCalled();
    },
  );

  it("does not let a callback captured before selection create after hydration", async () => {
    useOrgStore.setState({ activeOrgId: null });
    const { result } = renderHook(() => useCreateTeamRoom(), { wrapper });
    const beforeSelection = result.current.create;
    act(() => useOrgStore.setState({ activeOrgId: "org-a" }));
    expect(result.current.isReady).toBe(true);
    await act(async () => expect(beforeSelection("project-a", "Our team")).resolves.toBeNull());
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("propagates a creation failure while the identity is still current", async () => {
    const failure = new ApiError(403, "Project access changed");
    vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
    const { result } = renderHook(() => useCreateTeamRoom(), { wrapper });
    await act(async () =>
      expect(result.current.create("project-a", "Our team")).rejects.toBe(failure),
    );
  });
});

it("cancels a queued request through its room endpoint", async () => {
  const { result } = renderHook(() => useRoomActions("room-a"), { wrapper });
  await act(async () => result.current.cancel("request-a"));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/conversations/room-a/room-requests/request-a/cancel",
    {},
  );
});

describe("room cancellation ownership", () => {
  it.each([null, "room-b"])(
    "does not cancel through an unselected room %s",
    async (conversationId) => {
      const { result } = renderHook(() => useRoomActions(conversationId), { wrapper });
      await act(async () => result.current.cancel("request-a"));
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("propagates a current refusal without announcing or invalidating a successful cancellation", async () => {
    const failure = new ApiError(403, "Only its requester can cancel");
    vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const changed = vi.fn();
    const unsubscribe = onRoomChange(changed);
    const { result } = renderHook(() => useRoomActions("room-a"), { wrapper });
    try {
      await act(async () => expect(result.current.cancel("request-a")).rejects.toBe(failure));
      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
        "/conversations/room-a/room-requests/request-a/cancel",
        {},
      );
      expect(invalidate).not.toHaveBeenCalled();
      expect(changed).not.toHaveBeenCalled();
    } finally {
      unsubscribe();
    }
  });

  it.each(
    (["resolve", "reject"] as const).flatMap((outcome) =>
      (["conversation", "account", "organization", "unmount"] as const).map((boundary) => ({
        outcome,
        boundary,
      })),
    ),
  )("drops a cancellation $outcome after the $boundary changes", async ({ outcome, boundary }) => {
    const pending = deferred<unknown>();
    vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const changed = vi.fn();
    const unsubscribe = onRoomChange(changed);
    const { result, unmount } = renderHook(() => useRoomActions("room-a"), { wrapper });
    const cancelling = result.current.cancel("request-a");
    act(() => {
      if (boundary === "conversation")
        useConversationStore.setState({ currentConversationId: "room-b" });
      if (boundary === "account") useAuthStore.setState({ user: user("other") });
      if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-b" });
      if (boundary === "unmount") unmount();
    });
    try {
      await act(async () => {
        if (outcome === "resolve") pending.resolve({ id: "request-a", status: "cancelled" });
        else pending.reject(new ApiError(403, "Old room access changed"));
        await expect(cancelling).resolves.toBeUndefined();
      });
      expect(invalidate).not.toHaveBeenCalled();
      expect(changed).not.toHaveBeenCalled();
    } finally {
      unsubscribe();
    }
  });
});

function threadPage(root = "root-a", ids: string[] = [], total = ids.length): RoomThreadPage {
  return {
    root: {
      id: root,
      conversation_id: "room-a",
      role: "user",
      content: "Root",
      created_at: "2026-11-14T00:00:00Z",
    },
    items: ids.map((id) => ({
      id,
      conversation_id: "room-a",
      role: "user",
      content: id,
      created_at: "2026-11-14T00:00:00Z",
      thread_root_message_id: root,
    })),
    total,
    can_post: true,
  };
}

describe("room thread drafts", () => {
  it("does not post or create a retained attempt for an untouched empty draft", async () => {
    const { result } = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
    await act(async () => result.current.submit());
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(useChatStore.getState().roomDrafts).toEqual({});
  });

  it("posts an explicit thread root independently of the quoted message and main draft", async () => {
    useChatStore.setState({ replyTo: { messageId: "main-quote", role: "user", excerpt: "Main" } });
    const { result } = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
    act(() => {
      result.current.setContent("Thread answer");
      result.current.setAgentId("writer");
      result.current.setReply({
        messageId: "reply-in-a",
        role: "assistant",
        excerpt: "Earlier answer",
      });
    });
    await act(async () => result.current.submit());
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/room-a/room-messages", {
      client_message_id: expect.any(String),
      content: "Thread answer",
      agent_id: "writer",
      thread_root_message_id: "root-a",
      reply_to_message_id: "reply-in-a",
    });
    expect(result.current.reply).toBeNull();
    expect(useChatStore.getState().replyTo?.messageId).toBe("main-quote");
  });

  it("retains main and thread drafts and retries the original payload after switching roots", async () => {
    const hook = renderHook(({ root }: { root: string | null }) => useRoomDraft("room-a", root), {
      wrapper,
      initialProps: { root: null as string | null },
    });
    act(() => hook.result.current.setContent("Main draft"));
    hook.rerender({ root: "root-a" });
    act(() => {
      hook.result.current.setContent("Only in A");
      hook.result.current.setAgentId("writer");
      hook.result.current.setReply({ messageId: "root-a", role: "user", excerpt: "Root A" });
    });
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
    await act(async () => hook.result.current.submit());
    const frozen = vi.mocked(apiClient.post).mock.calls[0]![1];
    hook.rerender({ root: "root-b" });
    expect(hook.result.current.content).toBe("");
    expect(hook.result.current.reply).toBeNull();
    act(() => hook.result.current.setContent("Only in B"));
    await act(async () => hook.result.current.submit());
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toMatchObject({
      content: "Only in B",
      thread_root_message_id: "root-b",
    });
    hook.rerender({ root: "root-a" });
    expect(hook.result.current.retrying).toBe(true);
    expect(hook.result.current.content).toBe("Only in A");
    await act(async () => hook.result.current.submit());
    expect(vi.mocked(apiClient.post).mock.calls[2]![1]).toEqual(frozen);
    hook.rerender({ root: null });
    expect(hook.result.current.content).toBe("Main draft");
  });

  it("keeps a closed thread's uncertain token retryable after its late acknowledgement", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
    const first = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
    act(() => first.result.current.setContent("Once"));
    let posting!: Promise<void>;
    act(() => {
      posting = first.result.current.submit();
    });
    const frozen = vi.mocked(apiClient.post).mock.calls[0]![1];
    first.unmount();
    await act(async () => {
      pending.resolve(saved);
      await posting;
    });
    const reopened = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
    expect(reopened.result.current.retrying).toBe(true);
    await act(async () => reopened.result.current.submit());
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(frozen);
  });

  it("settles only the submitted root when another thread is edited before the ack", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
    const hook = renderHook(({ root }) => useRoomDraft("room-a", root), {
      wrapper,
      initialProps: { root: "root-a" },
    });
    act(() => hook.result.current.setContent("A"));
    let posting!: Promise<void>;
    act(() => {
      posting = hook.result.current.submit();
    });
    hook.rerender({ root: "root-b" });
    act(() => {
      hook.result.current.setContent("Keep B");
      hook.result.current.setReply({ messageId: "root-b", role: "user", excerpt: "B" });
    });
    await act(async () => {
      pending.resolve(saved);
      await posting;
    });
    expect(hook.result.current.content).toBe("Keep B");
    expect(hook.result.current.reply?.messageId).toBe("root-b");
    hook.rerender({ root: "root-a" });
    expect(hook.result.current.content).toBe("");
  });

  it.each(["resolve", "reject"] as const)(
    "a tenant reset wins over a late %s even after returning to the same identity",
    async (outcome) => {
      const pending = deferred<RoomMessageResult>();
      vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
      const hook = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
      act(() => hook.result.current.setContent("Old tenant draft"));
      let posting!: Promise<void>;
      act(() => {
        posting = hook.result.current.submit();
      });
      act(() => {
        resetTenantState();
        useConversationStore.setState({ currentConversationId: "room-a" });
      });
      await act(async () => {
        if (outcome === "resolve") pending.resolve(saved);
        else pending.reject(new ApiError(403, "Old refusal"));
        await posting;
      });
      expect(useChatStore.getState().roomDrafts).toEqual({});
      expect(hook.result.current.content).toBe("");
      expect(hook.result.current.error).toBeNull();
    },
  );

  it("preserves a newer thread quote and can cancel it without losing text", async () => {
    const pending = deferred<RoomMessageResult>();
    vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useRoomDraft("room-a", "root-a"), { wrapper });
    act(() => {
      result.current.setContent("A");
      result.current.setReply({ messageId: "old", role: "user", excerpt: "Old" });
    });
    let posting!: Promise<void>;
    act(() => {
      posting = result.current.submit();
    });
    act(() => result.current.setReply({ messageId: "new", role: "user", excerpt: "New" }));
    await act(async () => {
      pending.resolve(saved);
      await posting;
    });
    expect(result.current.reply?.messageId).toBe("new");
    act(() => {
      result.current.setContent("Next");
      result.current.clearReply();
    });
    expect(result.current.reply).toBeNull();
    expect(result.current.content).toBe("Next");
  });
});

describe("authorized thread history", () => {
  it("uses a root-specific cursor and oldest-to-newest pages", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      String(path).includes("before=reply-2")
        ? threadPage("root-a", ["reply-1"], 3)
        : path === "/orgs"
          ? { items: [] }
          : threadPage("root-a", ["reply-2", "reply-3"], 3),
    );
    const { result } = renderHook(() => useRoomThread("room-a", "root-a"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/conversations/room-a/room-threads/root-a?latest=true&limit=50",
    );
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(apiClient.get).toHaveBeenCalledWith(
      "/conversations/room-a/room-threads/root-a?latest=true&limit=50&before=reply-2",
    );
    await waitFor(() => expect(result.current.data?.pages[1]?.items[0]?.id).toBe("reply-1"));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("ends pagination on an empty page and encodes the root and cursor", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(threadPage("root /", [], 4));
    await getRoomThread("room-a", "root /", "reply /");
    expect(apiClient.get).toHaveBeenCalledWith(
      "/conversations/room-a/room-threads/root%20%2F?latest=true&limit=50&before=reply+%2F",
    );
    const { result } = renderHook(() => useRoomThread("room-a", "root /"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("invalidates only the current account, tenant and conversation on room events", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(threadPage());
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRoomThread("room-a", "root-a"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => {
      announceRoomChange({ conversationId: "room-b", accountId: "me", organizationId: "org-a" });
      announceRoomChange({ conversationId: "room-a", accountId: "other", organizationId: "org-a" });
      announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-b" });
    });
    expect(invalidate).not.toHaveBeenCalled();
    act(() =>
      announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: qk.roomThreads.detail("me", "org-a", "room-a", "root-a"),
    });
  });

  it("requires a fresh authorized read when reopening a cached thread", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(threadPage());
    client.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } });
    const first = renderHook(() => useRoomThread("room-a", "root-a"), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();
    const refused = deferred<RoomThreadPage>();
    vi.mocked(apiClient.get).mockReturnValue(refused.promise);
    const next = renderHook(() => useRoomThread("room-a", "root-a"), { wrapper });
    expect(next.result.current.isFetchedAfterMount).toBe(false);
    await act(async () => {
      refused.reject(new ApiError(403, "Revoked"));
    });
    await waitFor(() => expect(next.result.current.isError).toBe(true));
  });

  it.each([
    (page: RoomThreadPage) => {
      page.root.id = "wrong";
    },
    (page: RoomThreadPage) => {
      page.root.conversation_id = "wrong";
    },
    (page: RoomThreadPage) => {
      page.root.thread_root_message_id = "another-root";
    },
    (page: RoomThreadPage) => {
      page.root.role = "system";
    },
    (page: RoomThreadPage) => {
      page.items[0]!.conversation_id = "wrong";
    },
    (page: RoomThreadPage) => {
      page.items[0]!.thread_root_message_id = "wrong";
    },
  ])("rejects a response outside its requested scope (%#)", async (mutate) => {
    const page = threadPage("root-a", ["reply"]);
    mutate(page);
    vi.mocked(apiClient.get).mockResolvedValue(page);
    await expect(getRoomThread("room-a", "root-a")).rejects.toThrow("ROOM_THREAD_SCOPE_MISMATCH");
  });

  it("isolates cache entries across root, account, tenant and room", () => {
    const base = qk.roomThreads.detail("me", "org-a", "room-a", "root-a");
    expect([
      qk.roomThreads.detail("other", "org-a", "room-a", "root-a"),
      qk.roomThreads.detail("me", "org-b", "room-a", "root-a"),
      qk.roomThreads.detail("me", "org-a", "room-b", "root-a"),
      qk.roomThreads.detail("me", "org-a", "room-a", "root-b"),
    ]).not.toContainEqual(base);
  });

  it("does not read a thread without an account or selected root", async () => {
    useAuthStore.setState({ user: null });
    renderHook(() => useRoomThread("room-a", "root-a"), { wrapper });
    renderHook(() => useRoomThread(null, null), { wrapper });
    await act(async () => {});
    expect(
      vi.mocked(apiClient.get).mock.calls.some(([path]) => String(path).includes("room-threads")),
    ).toBe(false);
  });
});
