import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addRoomParticipant,
  createRoomConversation,
  getRoomDirectory,
  getRoomThread,
  getRoomParticipants,
  joinPublicRoom,
  removeRoomParticipant,
  updateRoomAgentAutoReply,
} from "./room-api";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("./api-client", () => ({ apiClient: api }));

beforeEach(() => vi.clearAllMocks());

describe("room participant API", () => {
  it("reads, adds, removes and updates participants on the room path", async () => {
    api.get.mockResolvedValue({ participants: [] });
    api.post.mockResolvedValue({ id: "p" });
    api.delete.mockResolvedValue(undefined);
    api.patch.mockResolvedValue({ id: "p" });

    await expect(getRoomParticipants("room-1")).resolves.toEqual({ participants: [] });
    await addRoomParticipant("room-1", { kind: "agent", id: "a" });
    await removeRoomParticipant("room-1", { kind: "user", id: "u/1" });
    await updateRoomAgentAutoReply("room-1", "a/1", true);

    expect(api.get).toHaveBeenCalledWith("/conversations/room-1/participants");
    expect(api.post).toHaveBeenCalledWith("/conversations/room-1/participants", {
      kind: "agent",
      id: "a",
    });
    expect(api.delete).toHaveBeenCalledWith("/conversations/room-1/participants/user/u%2F1");
    expect(api.patch).toHaveBeenCalledWith("/conversations/room-1/participants/agent/a%2F1", {
      auto_reply: true,
    });
  });
});

describe("room directory API", () => {
  it("creates, lists with default and explicit paging, and joins rooms", async () => {
    api.post.mockResolvedValue({ id: "room-1" });
    api.get.mockResolvedValue({ items: [] });

    await createRoomConversation({ title: "Ops" } as never);
    await getRoomDirectory();
    await getRoomDirectory(10, 5);
    await joinPublicRoom("room-1");

    expect(api.post).toHaveBeenNthCalledWith(1, "/conversations/rooms", { title: "Ops" });
    expect(api.get).toHaveBeenNthCalledWith(1, "/conversations/rooms", {
      params: { skip: "0", limit: "50" },
    });
    expect(api.get).toHaveBeenNthCalledWith(2, "/conversations/rooms", {
      params: { skip: "10", limit: "5" },
    });
    expect(api.post).toHaveBeenNthCalledWith(2, "/conversations/room-1/join", {});
  });
});

describe("room thread context validation", () => {
  const context = {
    source_conversation_id: "room-b",
    start_message_id: "start",
    end_message_id: "start",
    revision: 1,
    message_count: 1,
    message_ids: ["start"],
  };
  const row = { id: "start", conversation_id: "room-b", role: "user" };
  const page = (overrides: Record<string, unknown>) => ({
    conversation_id: "room-a",
    root: { id: "root", conversation_id: "room-a", role: "user" },
    items: [],
    context,
    context_messages: [row],
    ...overrides,
  });

  it("accepts a page whose context rows belong to the declared source", async () => {
    const accepted = page({});
    api.get.mockResolvedValue(accepted);
    await expect(getRoomThread("room-a", "root")).resolves.toEqual(accepted);
  });

  it.each([
    ["an empty source", { context: { ...context, source_conversation_id: "" } }],
    ["an empty start", { context: { ...context, start_message_id: "" } }],
    ["an empty end", { context: { ...context, end_message_id: "" } }],
    ["a negative revision", { context: { ...context, revision: -1 } }],
    ["a wrong message count", { context: { ...context, message_count: 2 } }],
    ["rows without a context", { context: null }],
    ["a row from another conversation", { context_messages: [{ ...row, conversation_id: "x" }] }],
    ["a system row", { context_messages: [{ ...row, role: "system" }] }],
    ["an undeclared row", { context_messages: [{ ...row, id: "other" }] }],
    ["a repeated row", { context_messages: [row, row] }],
  ])("refuses %s", async (_case, overrides) => {
    api.get.mockResolvedValue(page(overrides));
    await expect(getRoomThread("room-a", "root")).rejects.toThrow("ROOM_THREAD_SCOPE_MISMATCH");
  });
});
