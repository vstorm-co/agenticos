import { beforeEach, describe, expect, it, vi } from "vitest";
import { removeRoomMessageReaction, setRoomMessageReaction } from "./room-message-reactions-api";

const api = vi.hoisted(() => ({ put: vi.fn(), delete: vi.fn() }));
vi.mock("./api-client", () => ({ apiClient: api }));

beforeEach(() => vi.clearAllMocks());

describe("room message reaction API", () => {
  it("uses idempotent desired-state PUT and DELETE operations", async () => {
    api.put.mockResolvedValue({ reactions: [] });
    api.delete.mockResolvedValue({ reactions: [] });

    await setRoomMessageReaction("room / one", "message?one", "👍");
    await removeRoomMessageReaction("room / one", "message?one", "👍");

    const path = "/conversations/room%20%2F%20one/messages/message%3Fone/reactions";
    expect(api.put).toHaveBeenCalledWith(path, { emoji: "👍" });
    expect(api.delete).toHaveBeenCalledWith(path, { body: { emoji: "👍" } });
  });
});
