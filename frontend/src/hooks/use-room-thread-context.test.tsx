import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useRoomThreadContextActions,
  useRoomThreadContextConversationSearch,
} from "./use-room-thread-context";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextUpdateInput,
} from "@/types/room-thread-context";

const mocks = vi.hoisted(() => ({ update: vi.fn(), search: vi.fn() }));
let queryClient: QueryClient;

vi.mock("@/hooks/use-room", () => ({
  useRoomIdentity: () => ({
    accountId: "member",
    organizationId: "org-a",
    tenant: "org-a",
    current: () => true,
  }),
}));
vi.mock("@/lib/room-thread-context-api", () => ({
  createRoomThreadFromRange: vi.fn(),
  getRoomThreadContextCandidates: vi.fn(),
  getRoomThreadContextSourceConversation: vi.fn(),
  getRoomThreadContextSourcePage: vi.fn(),
  moveRoomThreadContext: vi.fn(),
  returnRoomThreadContext: vi.fn(),
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
  vi.clearAllMocks();
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
