import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addRoomParticipant,
  createRoomConversation,
  getRoomDirectory,
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
