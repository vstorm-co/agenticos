import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import type {
  Conversation,
  ConversationMessage,
  ConversationMessagesResponse,
} from "@/types/conversation";
import {
  getRoomThreadContextSourcePage,
  searchRoomThreadContextConversations,
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
