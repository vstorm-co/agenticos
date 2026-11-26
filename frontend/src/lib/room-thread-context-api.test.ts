import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import type {
  Conversation,
  ConversationMessage,
  ConversationMessagesResponse,
} from "@/types/conversation";
import {
  createRoomThreadFromRange,
  getRoomThreadContextCandidates,
  getRoomThreadContextSourceConversation,
  getRoomThreadContextSourcePage,
  moveRoomThreadContext,
  returnRoomThreadContext,
  searchRoomThreadContextConversations,
  updateRoomThreadContext,
} from "./room-thread-context-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function conversation(id: string, title: string): Conversation {
  return {
    id,
    title,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
  };
}

function message(id: string, role: ConversationMessage["role"]): ConversationMessage {
  return {
    id,
    conversation_id: "source-room",
    role,
    content: id,
    created_at: "2026-11-01T00:00:00Z",
  };
}

beforeEach(() => vi.clearAllMocks());

describe("room thread context source reads", () => {
  it("keeps shared conversation title matches reachable beyond the first fifty rows", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/conversations/shared-with-me")) {
        const skip = new URLSearchParams(path.split("?")[1]).get("skip");
        return {
          items:
            skip === "0"
              ? Array.from({ length: 50 }, (_, index) =>
                  conversation(`shared-${index}`, `General chat ${index}`),
                )
              : [conversation("shared-51", "Needle appears after page one")],
          total: 101,
        };
      }
      if (path.startsWith("/conversations/rooms")) return { items: [], total: 0 };
      if (path.startsWith("/conversations?")) return { items: [], total: 0 };
      throw new Error(`Unexpected read: ${path}`);
    });

    const first = await searchRoomThreadContextConversations("needle", {
      ownedSkip: 0,
      sharedSkip: 0,
      roomsSkip: 0,
    });
    expect(first.items).toEqual([]);
    expect(first.nextCursor).toEqual({ ownedSkip: null, sharedSkip: 50, roomsSkip: null });

    const second = await searchRoomThreadContextConversations("needle", first.nextCursor!);
    expect(second.items.map((item) => item.id)).toEqual(["shared-51"]);
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("filters system rows without losing the raw page cursor", async () => {
    const items = Array.from({ length: 101 }, (_, index) =>
      message(`message-${index}`, index === 0 ? "system" : index === 1 ? "assistant" : "user"),
    );
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      items,
      total: 250,
      cost: null,
    } satisfies ConversationMessagesResponse);

    const page = await getRoomThreadContextSourcePage("source-room");

    expect(page.items).toHaveLength(100);
    expect(page.items.some((item) => item.role === "system")).toBe(false);
    expect(page.rawCount).toBe(101);
    expect(page.total).toBe(250);
    expect(page.nextCursor).toBe("message-0");
  });
});

const range = { start_message_id: "a", end_message_id: "b" };

function action(
  context: Record<string, unknown> | null = {},
  overrides: Record<string, unknown> = {},
) {
  return {
    conversation_id: "room /a",
    root_message_id: "root",
    context: context === null ? null : { source_conversation_id: "room /a", ...context },
    ...overrides,
  };
}

describe("room thread context search", () => {
  const start = { ownedSkip: 0, sharedSkip: 0, roomsSkip: 0 };
  const found = (id: string, extra: Partial<Conversation> = {}) => ({
    ...conversation(id, "Needle " + id),
    ...extra,
  });
  const answer = (owned: object, shared: object, rooms: object) =>
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/conversations/shared-with-me")) return shared;
      if (path.startsWith("/conversations/rooms")) return rooms;
      return owned;
    });

  it("merges the three lists once each, newest first, and pages each separately", async () => {
    answer(
      { items: [found("owned", { updated_at: "2026-11-02T00:00:00Z" })], total: 2 },
      {
        items: [
          found("owned", { title: "Needle duplicate" }),
          found("archived", { is_archived: true }),
          found("untitled", { title: undefined }),
        ],
        total: 3,
      },
      {
        items: [
          found("public", { room_visibility: "public", updated_at: "2026-11-03T00:00:00Z" }),
          found("project", { project_id: "p" }),
          found("plain"),
          found("quiet", { room_visibility: "public", title: undefined }),
          found("owned", { project_id: "p", title: "Needle again" }),
        ],
        total: 9,
      },
    );

    const page = await searchRoomThreadContextConversations(" NEEDLE ", start);

    expect(page.items.map((item) => item.id)).toEqual(["public", "owned", "project"]);
    expect(page.items[1]?.title).toBe("Needle owned");
    expect(page.nextCursor).toEqual({ ownedSkip: 1, sharedSkip: null, roomsSkip: 5 });
  });

  it("stops paging when no list has more and skips the exhausted ones", async () => {
    answer({ items: [], total: 5 }, { items: [], total: 5 }, { items: [], total: 5 });
    const page = await searchRoomThreadContextConversations("needle", start);
    expect(page.nextCursor).toBeNull();

    vi.mocked(apiClient.get).mockClear();
    await expect(
      searchRoomThreadContextConversations("needle", {
        ownedSkip: null,
        sharedSkip: null,
        roomsSkip: null,
      }),
    ).resolves.toEqual({ items: [], nextCursor: null });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("room thread context reads", () => {
  it("returns only the source conversation that was asked for", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ id: "room /a" });
    await expect(getRoomThreadContextSourceConversation("room /a")).resolves.toEqual({
      id: "room /a",
    });
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/room%20%2Fa/metadata");

    vi.mocked(apiClient.get).mockResolvedValueOnce({ id: "other" });
    await expect(getRoomThreadContextSourceConversation("room /a")).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_SOURCE_SCOPE_MISMATCH",
    );
  });

  it("pages older source messages and ends on a short page", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      items: [message("one", "user")],
      total: 1,
    });
    const page = await getRoomThreadContextSourcePage("source-room", "cursor");
    expect(page.nextCursor).toBeNull();
    expect(vi.mocked(apiClient.get).mock.calls[0]?.[0]).toContain("before=cursor");
  });

  it.each([
    ["another conversation", { conversation_id: "elsewhere" }],
    ["a reply", { thread_root_message_id: "root" }],
  ])("refuses a source page holding %s", async (_case, overrides) => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      items: [{ ...message("one", "user"), ...overrides }],
      total: 1,
    });
    await expect(getRoomThreadContextSourcePage("source-room")).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_SOURCE_SCOPE_MISMATCH",
    );
  });

  const row = { id: "one", conversation_id: "source-room", role: "user" };
  const candidates = (overrides: Record<string, unknown> = {}) => ({
    source_conversation_id: "source-room",
    items: [row, { ...row, id: "two", thread_root_message_id: "root", deleted_at: "" }],
    total: 2,
    ...overrides,
  });

  it("accepts candidates from the source and this thread", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(candidates());
    await expect(getRoomThreadContextCandidates("room", "root")).resolves.toEqual(candidates());
  });

  const bad = (extra: Record<string, unknown>) => ({ items: [{ ...row, ...extra }], total: 1 });

  it.each([
    ["no list", { items: null }],
    ["a missing source", { source_conversation_id: null }],
    ["an empty source", { source_conversation_id: "" }],
    [
      "more than a thousand rows",
      { items: Array.from({ length: 1001 }, (_, i) => ({ ...row, id: String(i) })), total: 1001 },
    ],
    ["a wrong total", { total: 9 }],
    ["another conversation", bad({ conversation_id: "x" })],
    ["a system row", bad({ role: "system" })],
    ["a deleted row", bad({ deleted_at: "2026-11-01T00:00:00Z" })],
    ["another thread", bad({ thread_root_message_id: "other" })],
    ["a repeated row", { items: [row, row], total: 2 }],
  ])("refuses candidates with %s", async (_case, overrides) => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(candidates(overrides));
    await expect(getRoomThreadContextCandidates("room", "root")).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_CANDIDATES_SCOPE_MISMATCH",
    );
  });
});

describe("room thread context writes", () => {
  it("creates a thread from this room or the named source", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(action());
    await expect(createRoomThreadFromRange("room /a", range)).resolves.toEqual(action());
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/room%20%2Fa/room-threads", range);

    vi.mocked(apiClient.post).mockResolvedValueOnce(action());
    await expect(
      createRoomThreadFromRange("room /a", { ...range, source_conversation_id: "other" }),
    ).rejects.toThrow("ROOM_THREAD_CONTEXT_SOURCE_MISMATCH");
  });

  it.each([
    ["another conversation", action({}, { conversation_id: "x" })],
    ["no context", action(null)],
    ["an absent context", action({}, { context: undefined })],
    ["a missing source", action({ source_conversation_id: 1 })],
    ["an empty source", action({ source_conversation_id: "" })],
  ])("refuses a created thread answering with %s", async (_case, result) => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(result);
    await expect(createRoomThreadFromRange("room /a", range)).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_SCOPE_MISMATCH",
    );
  });

  it("confirms the thread and source of an update", async () => {
    const input = { ...range, expected_context_revision: 1 };
    vi.mocked(apiClient.patch).mockResolvedValueOnce(action());
    await expect(updateRoomThreadContext("room /a", "root", input)).resolves.toEqual(action());

    vi.mocked(apiClient.patch).mockResolvedValueOnce(action({}, { root_message_id: "x" }));
    await expect(updateRoomThreadContext("room /a", "root", input)).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_SCOPE_MISMATCH",
    );

    vi.mocked(apiClient.patch).mockResolvedValueOnce(action());
    await expect(
      updateRoomThreadContext("room /a", "root", { ...input, source_conversation_id: "other" }),
    ).rejects.toThrow("ROOM_THREAD_CONTEXT_SOURCE_MISMATCH");

    vi.mocked(apiClient.patch).mockResolvedValueOnce(action());
    await expect(
      updateRoomThreadContext("room /a", "root", { ...input, source_conversation_id: "room /a" }),
    ).resolves.toEqual(action());
  });

  it("reports a move or return only when the server says it happened", async () => {
    const input = { expected_context_revision: 1 };
    const moved = action({ moved: true });
    const here = action({ moved: false });

    vi.mocked(apiClient.post).mockResolvedValueOnce(moved);
    await expect(moveRoomThreadContext("room /a", "root", input)).resolves.toEqual(moved);
    vi.mocked(apiClient.post).mockResolvedValueOnce(here);
    await expect(moveRoomThreadContext("room /a", "root", input)).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_MOVE_NOT_CONFIRMED",
    );
    vi.mocked(apiClient.post).mockResolvedValueOnce(here);
    await expect(returnRoomThreadContext("room /a", "root", input)).resolves.toEqual(here);
    vi.mocked(apiClient.post).mockResolvedValueOnce(moved);
    await expect(returnRoomThreadContext("room /a", "root", input)).rejects.toThrow(
      "ROOM_THREAD_CONTEXT_RETURN_NOT_CONFIRMED",
    );
  });
});
