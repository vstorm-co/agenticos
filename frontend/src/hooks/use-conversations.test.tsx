import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useConversations } from "./use-conversations";
import { apiClient } from "@/lib/api-client";
import { useAgentSelectionStore, useAuthStore, useChatStore, useConversationStore } from "@/stores";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function conversation(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: `Conversation ${id}`,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
    ...overrides,
  };
}

/** The list route, plus whatever `/messages` should answer with. */
function serve({
  items = [conversation("c-1")],
  messages = [{ id: "m-1", role: "user", content: "hi" }],
}: { items?: unknown[]; messages?: unknown[] } = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/messages")) return { items: messages, total: messages.length };
    return { items, total: items.length };
  });
}

async function hook() {
  const rendered = renderHook(() => useConversations(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/chat");
  useConversationStore.getState().reset();
  useChatStore.setState({ messages: [], isStreaming: false });
  useAgentSelectionStore.setState({ selectedAgentId: null, defaultAgentId: null });
  serve();
  vi.mocked(apiClient.post).mockResolvedValue(conversation("c-new"));
  vi.mocked(apiClient.patch).mockResolvedValue({});
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

/**
 * The conversation sidebar and what is open in it.
 *
 * Three rules here are the ones that produce bug reports when they break.
 *
 * A rapid switch between conversations aborts the previous message fetch: without
 * it, a slower earlier request resolves last and the messages of a conversation
 * nobody is looking at appear under the title of the one they are.
 *
 * The `?id=` parameter is the source of truth on load - a link somebody was sent
 * has to win over whatever the store persisted - and an id that cannot be read is
 * cleared rather than left selected against an empty thread.
 *
 * Starting a new chat reuses the current conversation when it is empty. Otherwise
 * every stray click on "New chat" leaves an untitled empty row in the sidebar.
 */
describe("the conversation list", () => {
  it("reads active and archived in one call, so the tabs can split them", async () => {
    const result = await hook();

    expect(result.current.conversations).toHaveLength(1);
    expect(apiClient.get).toHaveBeenCalledWith("/conversations?limit=30&include_archived=true");
  });

  it("says there is more to load only when the page came back full", async () => {
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();

    expect(result.current.hasMore).toBe(true);
  });

  it("says there is no more when the page came back short", async () => {
    const result = await hook();

    expect(result.current.hasMore).toBe(false);
  });

  it("appends the next page from where the list ends", async () => {
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();

    serve({ items: [conversation("c-later")] });
    await act(async () => {
      await result.current.fetchMoreConversations();
    });

    expect(apiClient.get).toHaveBeenCalledWith(
      "/conversations?limit=30&skip=30&include_archived=true",
    );
    await waitFor(() => expect(result.current.conversations).toHaveLength(31));
  });

  it("does not list a conversation twice when a refetch raced the append", async () => {
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();

    await act(async () => {
      await result.current.fetchMoreConversations();
    });

    expect(result.current.conversations).toHaveLength(30);
  });

  it("asks for no further page once the list is exhausted", async () => {
    const result = await hook();
    const before = vi.mocked(apiClient.get).mock.calls.length;

    await act(async () => {
      await result.current.fetchMoreConversations();
    });

    expect(vi.mocked(apiClient.get).mock.calls.length).toBe(before);
  });

  it("does not fire two page loads at once", async () => {
    // The sidebar's scroll handler fires repeatedly; two in flight would append
    // the same page twice.
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();
    const before = vi.mocked(apiClient.get).mock.calls.length;

    await act(async () => {
      await Promise.all([
        result.current.fetchMoreConversations(),
        result.current.fetchMoreConversations(),
      ]);
    });

    expect(vi.mocked(apiClient.get).mock.calls.length).toBe(before + 1);
  });

  it("survives a refused next page without emptying the list", async () => {
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();

    vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
    await act(async () => {
      await result.current.fetchMoreConversations();
    });

    expect(result.current.conversations).toHaveLength(30);
  });

  it("drops a next page that arrives after somebody else has signed in", async () => {
    // Writing the cache is not the same as reading it: the sign-in that emptied
    // it has already happened, so this would put one page of A's titles back
    // under the key B is reading.
    useAuthStore.getState().setUser({ id: "u-a", email: "a@example.com" } as never);
    serve({ items: Array.from({ length: 30 }, (_, index) => conversation(`c-${index}`)) });
    const result = await hook();

    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    let loading: Promise<void>;
    await act(async () => {
      loading = result.current.fetchMoreConversations();
      await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    });

    await act(async () => {
      useAuthStore.getState().setUser({ id: "u-b", email: "b@example.com" } as never);
      answer({ items: [conversation("c-private")], total: 31 });
      await loading!;
    });

    expect(result.current.conversations.map((c) => c.id)).not.toContain("c-private");
  });

  it("refreshes the list on demand", async () => {
    const result = await hook();

    await act(async () => {
      await result.current.fetchConversations();
    });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});

describe("the conversation named in the address bar", () => {
  it("opens the one the link points at, and its messages", async () => {
    // A shared link has to win over whatever the store remembered.
    window.history.replaceState({}, "", "/chat?id=c-9");
    const result = await hook();

    await act(async () => {
      await result.current.fetchConversations();
    });

    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c-9/messages");
    expect(useConversationStore.getState().currentConversationId).toBe("c-9");
    expect(useConversationStore.getState().currentMessages).toHaveLength(1);
  });

  it("clears an id it cannot read rather than showing an empty thread under it", async () => {
    // A deleted conversation, or one belonging to somebody else.
    window.history.replaceState({}, "", "/chat?id=c-gone");
    const result = await hook();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/messages")) throw new Error("404");
      return { items: [], total: 0 };
    });

    await act(async () => {
      await result.current.fetchConversations();
    });

    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });

  it("drops a linked thread that arrives after somebody else has signed in", async () => {
    // Same race as a select, through the other door: the address bar's `?id=`
    // is read on every refresh, and its request can outlive the session too.
    window.history.replaceState({}, "", "/chat?id=c-9");
    useAuthStore.getState().setUser({ id: "u-a", email: "a@example.com" } as never);
    const result = await hook();
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/messages")) return new Promise((resolve) => (answer = resolve));
      return { items: [], total: 0 };
    });

    let fetching: Promise<void>;
    await act(async () => {
      fetching = result.current.fetchConversations();
      await waitFor(() =>
        expect(apiClient.get).toHaveBeenCalledWith("/conversations/c-9/messages"),
      );
    });

    await act(async () => {
      useAuthStore.getState().setUser({ id: "u-b", email: "b@example.com" } as never);
      answer({ items: [{ id: "m-private" }], total: 1 });
      await fetching!;
    });

    expect(useConversationStore.getState().currentMessages).toEqual([]);
  });

  it("does not re-read the messages of the conversation already open", async () => {
    window.history.replaceState({}, "", "/chat?id=c-1");
    useConversationStore.getState().setCurrentConversationId("c-1");
    const result = await hook();

    await act(async () => {
      await result.current.fetchConversations();
    });

    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/c-1/messages");
  });
});

describe("opening a conversation", () => {
  it("reads its messages and puts it in the address bar", async () => {
    // So a refresh, or a link somebody copies, lands back on the same thread.
    const result = await hook();

    await act(async () => {
      await result.current.selectConversation("c-1");
    });

    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c-1/messages", {
      signal: expect.any(AbortSignal),
    });
    expect(window.location.search).toBe("?id=c-1");
    expect(useConversationStore.getState().currentMessages).toHaveLength(1);
  });

  it("clears the streamed messages of the thread being left", async () => {
    // Otherwise the previous conversation's live bubbles render above the new
    // conversation's history.
    const result = await hook();
    useChatStore.getState().addMessage({
      id: "m-live",
      role: "assistant",
      content: "from the last thread",
      timestamp: new Date("2026-07-31T12:00:00Z"),
    });

    await act(async () => {
      await result.current.selectConversation("c-1");
    });

    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("abandons a slower earlier fetch rather than letting it win", async () => {
    // The bug this exists for: click A, click B, and A's messages arrive last and
    // render under B's title.
    const result = await hook();
    const pending = new Map<string, (value: unknown) => void>();
    vi.mocked(apiClient.get).mockImplementation(
      (path: string) =>
        new Promise((resolve) => {
          pending.set(path, resolve);
        }),
    );

    let first: Promise<void>;
    let second: Promise<void>;
    await act(async () => {
      first = result.current.selectConversation("c-1");
      second = result.current.selectConversation("c-2");
      await waitFor(() => expect(pending.size).toBe(2));
    });

    await act(async () => {
      // The superseded request answers last, with the wrong thread's messages.
      pending.get("/conversations/c-2/messages")!({ items: [{ id: "m-2" }], total: 1 });
      pending.get("/conversations/c-1/messages")!({ items: [{ id: "m-1" }], total: 1 });
      await Promise.all([first!, second!]);
    });

    expect(useConversationStore.getState().currentConversationId).toBe("c-2");
    expect(useConversationStore.getState().currentMessages).toEqual([{ id: "m-2" }]);
  });

  it("drops messages that arrive after somebody else has signed in", async () => {
    // The abort controller settles two selects by the same person. It does not
    // settle a request that outlives the session: A opens a thread, signs out,
    // B signs in, and A's messages land in B's chat.
    useAuthStore.getState().setUser({ id: "u-a", email: "a@example.com" } as never);
    const result = await hook();
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(() => new Promise((resolve) => (answer = resolve)));

    let selecting: Promise<void>;
    await act(async () => {
      selecting = result.current.selectConversation("c-1");
      await waitFor(() => expect(answer).not.toBe(undefined));
    });

    await act(async () => {
      useAuthStore.getState().setUser({ id: "u-b", email: "b@example.com" } as never);
      answer({ items: [{ id: "m-private" }], total: 1 });
      await selecting!;
    });

    expect(useConversationStore.getState().currentMessages).toEqual([]);
  });

  it("says nothing about an aborted request, because it was not a failure", async () => {
    const result = await hook();
    vi.mocked(apiClient.get).mockRejectedValue(
      new DOMException("The operation was aborted", "AbortError"),
    );

    await act(async () => {
      await result.current.selectConversation("c-1");
    });

    expect(useConversationStore.getState().error).toBeNull();
  });

  it("says what went wrong when the messages cannot be read", async () => {
    const result = await hook();
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Not your conversation"));

    await act(async () => {
      await result.current.selectConversation("c-1");
    });

    expect(useConversationStore.getState().error).toBe("Not your conversation");
    expect(useConversationStore.getState().isLoading).toBe(false);
  });

  it("falls back to its own sentence for a failure that carries none", async () => {
    const result = await hook();
    vi.mocked(apiClient.get).mockRejectedValue("boom");

    await act(async () => {
      await result.current.selectConversation("c-1");
    });

    expect(useConversationStore.getState().error).toBe("Failed to fetch messages");
  });
});

describe("creating, renaming and removing a conversation", () => {
  it("puts a new conversation at the top of the list", async () => {
    const result = await hook();
    vi.mocked(apiClient.post).mockResolvedValue(conversation("c-new", { title: "Refunds" }));

    let created: unknown;
    await act(async () => {
      created = await result.current.createConversation("Refunds");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/conversations", { title: "Refunds" });
    expect(created).toMatchObject({ id: "c-new", title: "Refunds" });
    await waitFor(() => expect(result.current.conversations[0]?.id).toBe("c-new"));
  });

  it("hands back nothing and says why when creation is refused", async () => {
    const result = await hook();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Rate limited"));

    let created: unknown;
    await act(async () => {
      created = await result.current.createConversation();
    });

    expect(created).toBeNull();
    expect(useConversationStore.getState().error).toBe("Rate limited");
    expect(useConversationStore.getState().isLoading).toBe(false);
  });

  it("falls back to its own sentence when creation fails without one", async () => {
    const result = await hook();
    vi.mocked(apiClient.post).mockRejectedValue("boom");

    await act(async () => {
      await result.current.createConversation();
    });

    expect(useConversationStore.getState().error).toBe("Failed to create conversation");
  });

  it("archives and restores in place, so the row moves tab without a refetch", async () => {
    const result = await hook();

    await act(async () => {
      await result.current.archiveConversation("c-1");
    });
    expect(apiClient.patch).toHaveBeenCalledWith("/conversations/c-1", { is_archived: true });
    await waitFor(() => expect(result.current.conversations[0]?.is_archived).toBe(true));

    await act(async () => {
      await result.current.unarchiveConversation("c-1");
    });
    expect(apiClient.patch).toHaveBeenCalledWith("/conversations/c-1", { is_archived: false });
    await waitFor(() => expect(result.current.conversations[0]?.is_archived).toBe(false));
  });

  it("reports a refused archive and a refused restore", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockRejectedValue("boom");

    await act(async () => {
      await result.current.archiveConversation("c-1");
    });
    expect(toast.error).toHaveBeenCalledWith("Failed to archive conversation");

    await act(async () => {
      await result.current.unarchiveConversation("c-1");
    });
    expect(toast.error).toHaveBeenCalledWith("Failed to restore conversation");
  });

  it("renames in place", async () => {
    const result = await hook();

    await act(async () => {
      await result.current.renameConversation("c-1", "Refund policy");
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/conversations/c-1", { title: "Refund policy" });
    await waitFor(() => expect(result.current.conversations[0]?.title).toBe("Refund policy"));
  });

  it("reports a refused rename", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Too long"));

    await act(async () => {
      await result.current.renameConversation("c-1", "x");
    });

    expect(toast.error).toHaveBeenCalledWith("Too long");
  });

  it("drops a deleted conversation, and clears the selection if it was open", async () => {
    const result = await hook();
    useConversationStore.getState().setCurrentConversationId("c-1");

    await act(async () => {
      await result.current.deleteConversation("c-1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/conversations/c-1");
    await waitFor(() => expect(result.current.conversations).toEqual([]));
    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });

  it("keeps the selection when a different conversation is deleted", async () => {
    serve({ items: [conversation("c-1"), conversation("c-2")] });
    const result = await hook();
    useConversationStore.getState().setCurrentConversationId("c-1");

    await act(async () => {
      await result.current.deleteConversation("c-2");
    });

    expect(useConversationStore.getState().currentConversationId).toBe("c-1");
  });

  it("reports a refused deletion", async () => {
    const result = await hook();
    vi.mocked(apiClient.delete).mockRejectedValue("boom");

    await act(async () => {
      await result.current.deleteConversation("c-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to delete conversation");
  });
});

describe("a request that outlives the account that made it", () => {
  it("keeps a conversation created by one account out of the next one's list", async () => {
    // The one write that adds a row rather than mapping over the rows already
    // there, so it is the one that can put A's conversation in B's sidebar.
    useAuthStore.getState().setUser({ id: "u-a", email: "a@example.com" } as never);
    const result = await hook();

    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => (answer = resolve)),
    );
    let creating: Promise<unknown>;
    await act(async () => {
      creating = result.current.createConversation("A's thread");
      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    });

    await act(async () => {
      useAuthStore.getState().setUser({ id: "u-b", email: "b@example.com" } as never);
      answer({
        id: "c-private",
        title: "A's thread",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: null,
        is_archived: false,
      });
      await creating!;
    });

    expect(result.current.conversations.map((c) => c.id)).not.toContain("c-private");
  });
});

describe("starting a new chat", () => {
  it("reuses the conversation already open when it is empty", async () => {
    // Otherwise every stray click leaves an untitled empty row in the sidebar.
    const result = await hook();
    useConversationStore.getState().setCurrentConversationId("c-1");
    useConversationStore.getState().setCurrentMessages([]);
    window.history.replaceState({}, "", "/chat?id=c-1");

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(useConversationStore.getState().currentConversationId).toBe("c-1");
    expect(window.location.search).toBe("?id=c-1");
  });

  it("leaves a conversation that has messages, and strips the stale id at once", async () => {
    // A refresh mid-flight has to land on a fresh chat rather than the old thread;
    // the new id arrives over the websocket with the first message.
    const result = await hook();
    useConversationStore.getState().setCurrentConversationId("c-1");
    useConversationStore
      .getState()
      .setCurrentMessages([{ id: "m-1", role: "user", content: "hi" } as never]);
    window.history.replaceState({}, "", "/chat?id=c-1");

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useConversationStore.getState().currentMessages).toEqual([]);
    expect(window.location.search).toBe("");
  });

  it("starts a fresh chat when nothing was open", async () => {
    const result = await hook();

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });

  it("starts on the starred agent, which is what makes a default a default", async () => {
    // Mid-thread switches stay per-thread; a new chat is the reset point.
    const result = await hook();
    useAgentSelectionStore.setState({ selectedAgentId: "a-other", defaultAgentId: "a-default" });

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-default");
  });

  it("leaves the selection alone when nobody starred an agent", async () => {
    const result = await hook();
    useAgentSelectionStore.setState({ selectedAgentId: "a-other", defaultAgentId: null });

    await act(async () => {
      await result.current.startNewChat();
    });

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-other");
  });
});
