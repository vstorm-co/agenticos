import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  threadRootFromAction,
  useRoomThreadContextActions,
  useRoomThreadContextCandidates,
  useRoomThreadContextConversationSearch,
  useRoomThreadContextSource,
  useRoomThreadContextSourceConversation,
} from "./use-room-thread-context";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextUpdateInput,
} from "@/types/room-thread-context";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  move: vi.fn(),
  giveBack: vi.fn(),
  search: vi.fn(),
  candidates: vi.fn(),
  conversation: vi.fn(),
  page: vi.fn(),
  current: vi.fn(() => true),
}));
let queryClient: QueryClient;

vi.mock("@/hooks/use-room", () => ({
  useRoomIdentity: () => ({
    accountId: "member",
    organizationId: "org-a",
    tenant: "org-a",
    current: mocks.current,
  }),
}));
vi.mock("@/lib/room-thread-context-api", () => ({
  createRoomThreadFromRange: mocks.create,
  getRoomThreadContextCandidates: mocks.candidates,
  getRoomThreadContextSourceConversation: mocks.conversation,
  getRoomThreadContextSourcePage: mocks.page,
  moveRoomThreadContext: mocks.move,
  returnRoomThreadContext: mocks.giveBack,
  searchRoomThreadContextConversations: mocks.search,
  updateRoomThreadContext: mocks.update,
}));

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

function actionRead(): RoomThreadContextActionRead {
  return {
    conversation_id: "room-a",
    root_message_id: "root-a",
    state: "open",
    following: false,
    unread: 0,
    can_manage: true,
    context: {
      source_conversation_id: "room-a",
      start_message_id: "start",
      end_message_id: "end",
      first_ordinal: 1,
      last_ordinal: 2,
      excluded_message_ids: [],
      message_ids: ["start", "end"],
      message_count: 2,
      moved: false,
      revision: 2,
    },
  };
}

const input: RoomThreadContextUpdateInput = {
  start_message_id: "start",
  end_message_id: "end",
  expected_context_revision: 1,
};

function conversation(id: string, title: string) {
  return {
    id,
    title,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.current.mockReturnValue(true);
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useAuthStore.setState({
    user: {
      id: "member",
      email: "member@example.com",
      is_active: true,
      created_at: "2026-11-01T00:00:00Z",
    },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a", selectionVersion: 1 });
});

describe("useRoomThreadContextConversationSearch", () => {
  it("deduplicates overlapping source pages by conversation ID", async () => {
    mocks.search
      .mockResolvedValueOnce({
        items: [conversation("shared", "First copy"), conversation("first", "First result")],
        nextCursor: { ownedSkip: null, sharedSkip: 50, roomsSkip: null },
      })
      .mockResolvedValueOnce({
        items: [conversation("shared", "Duplicate copy"), conversation("later", "Later result")],
        nextCursor: null,
      });
    const { result } = renderHook(() => useRoomThreadContextConversationSearch("needle"), {
      wrapper,
    });
    await waitFor(() =>
      expect(result.current.items.map((item) => item.id)).toEqual(["shared", "first"]),
    );

    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() =>
      expect(result.current.items.map((item) => item.id)).toEqual(["shared", "first", "later"]),
    );
    expect(result.current.items[0]?.title).toBe("First copy");
  });
});

describe("useRoomThreadContextActions response scope", () => {
  it("drops a delayed mutation result after switching A to B and back to A", async () => {
    const pending = deferred<RoomThreadContextActionRead>();
    mocks.update.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useRoomThreadContextActions("room-a", "root-a"), {
      wrapper,
    });
    let operation!: Promise<RoomThreadContextActionRead | null>;
    act(() => {
      operation = result.current.updateContext(input);
    });

    act(() =>
      useConversationStore.setState({ currentConversationId: "room-b", selectionVersion: 2 }),
    );
    act(() =>
      useConversationStore.setState({ currentConversationId: "room-a", selectionVersion: 3 }),
    );
    await act(async () => {
      pending.resolve(actionRead());
      expect(await operation).toBeNull();
    });

    expect(mocks.update).toHaveBeenCalledWith("room-a", "root-a", input);
  });

  it.each(["root", "editor"] as const)(
    "drops a delayed mutation result after the %s changes",
    async (scope) => {
      const pending = deferred<RoomThreadContextActionRead>();
      mocks.update.mockReturnValueOnce(pending.promise);
      const { result, rerender } = renderHook(
        ({ root, lifetime }: { root: string; lifetime: number }) =>
          useRoomThreadContextActions("room-a", root, lifetime),
        { wrapper, initialProps: { root: "root-a", lifetime: 0 } },
      );
      let operation!: Promise<RoomThreadContextActionRead | null>;
      act(() => {
        operation = result.current.updateContext(input);
      });

      rerender({
        root: scope === "root" ? "root-b" : "root-a",
        lifetime: scope === "editor" ? 1 : 0,
      });
      await act(async () => {
        pending.resolve(actionRead());
        expect(await operation).toBeNull();
      });
    },
  );
});

const scope = { accountId: "member", organizationId: "org-a" };
const sourcePage = (id: string, nextCursor: string | null = null, total = 1) => ({
  items: [{ id }],
  total,
  rawCount: 1,
  nextCursor,
});

describe("useRoomThreadContextSource", () => {
  it("lists older pages first and rereads when the source room changes", async () => {
    mocks.page.mockImplementation(async (_id: string, before: string | null) =>
      before === null ? sourcePage("newer", "newer", 2) : sourcePage("older", "older", 2),
    );
    const { result } = renderHook(() => useRoomThreadContextSource("room-b"), { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() =>
      expect(result.current.messages.map((item) => item.id)).toEqual(["older", "newer"]),
    );
    expect(result.current.hasNextPage).toBe(false);

    const reads = mocks.page.mock.calls.length;
    act(() => announceRoomChange({ ...scope, conversationId: "unrelated" }));
    expect(mocks.page).toHaveBeenCalledTimes(reads);
    act(() => announceRoomChange({ ...scope, conversationId: "room-b" }));
    await waitFor(() => expect(mocks.page.mock.calls.length).toBeGreaterThan(reads));
  });

  it("reads nothing without a source or while closed", () => {
    renderHook(() => useRoomThreadContextSource(null), { wrapper });
    renderHook(() => useRoomThreadContextSource("room-b", false), { wrapper });
    expect(mocks.page).not.toHaveBeenCalled();
  });

  it.each(["before", "after"] as const)(
    "fails the read when the identity changes %s the request",
    async (when) => {
      mocks.current.mockReturnValue(false);
      if (when === "after") mocks.current.mockReturnValueOnce(true);
      mocks.page.mockResolvedValue(sourcePage("one"));
      const { result } = renderHook(() => useRoomThreadContextSource("room-b"), { wrapper });
      await waitFor(() =>
        expect(result.current.error?.message).toBe("ROOM_THREAD_CONTEXT_SCOPE_CHANGED"),
      );
      expect(result.current.messages).toEqual([]);
    },
  );
});

describe("the other room thread context reads", () => {
  /** One probe hook for the three reads, so each case fails or passes on its error alone. */
  function useRead(read: "search" | "conversation" | "candidates"): { error: Error | null } {
    const search = useRoomThreadContextConversationSearch("needle");
    const source = useRoomThreadContextSourceConversation("room-b", read === "conversation");
    const candidates = useRoomThreadContextCandidates("room-a", "root-a", 1, read === "candidates");
    return { search, conversation: source, candidates }[read];
  }

  it.each(
    (["search", "conversation", "candidates"] as const).flatMap((read) =>
      (["before", "after"] as const).map((when) => [read, when] as const),
    ),
  )("fails the %s read when the identity changes %s the request", async (read, when) => {
    mocks.current.mockReturnValue(false);
    if (when === "after") mocks.current.mockReturnValueOnce(true);
    mocks[read].mockResolvedValue({ items: [], nextCursor: null });
    const { result } = renderHook(() => useRead(read), { wrapper });
    await waitFor(() =>
      expect(result.current.error?.message).toBe("ROOM_THREAD_CONTEXT_SCOPE_CHANGED"),
    );
  });

  it("returns the source conversation and skips it when there is none", async () => {
    mocks.conversation.mockResolvedValue({ id: "room-b" });
    const { result } = renderHook(() => useRoomThreadContextSourceConversation("room-b"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.data).toEqual({ id: "room-b" }));
    renderHook(() => useRoomThreadContextSourceConversation(null), { wrapper });
    expect(mocks.conversation).toHaveBeenCalledTimes(1);
  });

  it("orders search results by their last change", async () => {
    mocks.search.mockResolvedValue({
      items: [
        conversation("old", "Old"),
        { ...conversation("new", "New"), updated_at: "2026-11-05T00:00:00Z" },
      ],
      nextCursor: null,
    });
    const { result } = renderHook(() => useRoomThreadContextConversationSearch("needle"), {
      wrapper,
    });
    await waitFor(() =>
      expect(result.current.items.map((item) => item.id)).toEqual(["new", "old"]),
    );
  });

  it("rereads candidates when either room changes", async () => {
    mocks.candidates.mockResolvedValue({ source_conversation_id: "room-b", items: [] });
    const { result } = renderHook(
      () => useRoomThreadContextCandidates("room-a", "root-a", 1, true, "room-b"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    for (const conversationId of ["room-a", "room-b"]) {
      const reads = mocks.candidates.mock.calls.length;
      act(() => announceRoomChange({ ...scope, conversationId }));
      await waitFor(() => expect(mocks.candidates.mock.calls.length).toBeGreaterThan(reads));
    }
    const reads = mocks.candidates.mock.calls.length;
    act(() => announceRoomChange({ ...scope, conversationId: "unrelated" }));
    expect(mocks.candidates).toHaveBeenCalledTimes(reads);
  });

  it("refuses candidates read from a different source", async () => {
    mocks.candidates.mockResolvedValue({ source_conversation_id: "room-c", items: [] });
    const { result } = renderHook(
      () => useRoomThreadContextCandidates("room-a", "root-a", 1, true, "room-b"),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.error?.message).toBe("ROOM_THREAD_CONTEXT_CANDIDATES_SCOPE_MISMATCH"),
    );
  });
});

describe("useRoomThreadContextActions writes", () => {
  const mutation = { expected_context_revision: 1 };

  it("sends each write for the open thread and tells the room", async () => {
    for (const write of [mocks.create, mocks.update, mocks.move, mocks.giveBack]) {
      write.mockResolvedValue(actionRead());
    }
    const changed = vi.fn();
    const unsubscribe = onRoomChange(changed);
    const { result } = renderHook(() => useRoomThreadContextActions("room-a", "root-a"), {
      wrapper,
    });

    await act(async () => {
      expect(await result.current.createFromRange(input)).toEqual(actionRead());
      expect(await result.current.updateContext(input)).toEqual(actionRead());
      expect(await result.current.moveContext(mutation)).toEqual(actionRead());
      expect(await result.current.returnContext(mutation)).toEqual(actionRead());
    });

    expect(mocks.create).toHaveBeenCalledWith("room-a", input);
    expect(mocks.move).toHaveBeenCalledWith("room-a", "root-a", mutation);
    expect(mocks.giveBack).toHaveBeenCalledWith("room-a", "root-a", mutation);
    expect(changed).toHaveBeenCalledTimes(4);
    expect(result.current.isPending).toBe(false);
    unsubscribe();
  });

  it("creates without a thread but writes nothing else", async () => {
    mocks.create.mockResolvedValue(actionRead());
    const { result } = renderHook(() => useRoomThreadContextActions("room-a"), { wrapper });
    await act(async () => {
      expect(await result.current.createFromRange(input)).toEqual(actionRead());
      expect(await result.current.updateContext(input)).toBeNull();
      expect(await result.current.moveContext(mutation)).toBeNull();
      expect(await result.current.returnContext(mutation)).toBeNull();
    });
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.move).not.toHaveBeenCalled();
  });

  it("writes nothing without a conversation or after the view moved on", async () => {
    const none = renderHook(() => useRoomThreadContextActions(null, "root-a"), { wrapper });
    const other = renderHook(() => useRoomThreadContextActions("room-z", "root-a"), { wrapper });
    await act(async () => {
      expect(await none.result.current.createFromRange(input)).toBeNull();
      expect(await none.result.current.updateContext(input)).toBeNull();
      expect(await none.result.current.moveContext(mutation)).toBeNull();
      expect(await none.result.current.returnContext(mutation)).toBeNull();
      expect(await other.result.current.updateContext(input)).toBeNull();
    });
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("surfaces a failure only to the view that asked", async () => {
    const { result } = renderHook(() => useRoomThreadContextActions("room-a", "root-a"), {
      wrapper,
    });
    mocks.update.mockRejectedValueOnce(new Error("refused"));
    await act(async () => {
      await expect(result.current.updateContext(input)).rejects.toThrow("refused");
    });

    mocks.update.mockImplementationOnce(async () => {
      useConversationStore.setState({ currentConversationId: "room-b", selectionVersion: 2 });
      throw new Error("late");
    });
    await act(async () => {
      expect(await result.current.updateContext(input)).toBeNull();
    });
  });

  it("opens the thread the server named", () => {
    expect(threadRootFromAction(actionRead())).toBe("root-a");
  });
});
