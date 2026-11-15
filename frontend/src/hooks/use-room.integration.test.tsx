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
  useChatStore.setState({ messages: [], replyTo: null });
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
    expect(result.current.content).toBe("The original draft");
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
