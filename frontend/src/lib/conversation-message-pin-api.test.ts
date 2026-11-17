import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  listConversationMessagePins,
  pinConversationMessage,
  unpinConversationMessage,
} from "./conversation-message-pin-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => vi.resetAllMocks());

describe("conversation message pin transport", () => {
  it("fetches a bounded page and forwards cancellation", async () => {
    const page = { items: [], total: 0 };
    const signal = new AbortController().signal;
    vi.mocked(apiClient.get).mockResolvedValueOnce(page);

    await expect(listConversationMessagePins("chat/one", 50, signal)).resolves.toBe(page);

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith(
      "/conversations/chat%2Fone/message-pins",
      { params: { skip: "50", limit: "50" }, signal },
    );
  });

  it("pins and unpins a message using encoded path segments", async () => {
    const pin = { message_id: "m/1" };
    vi.mocked(apiClient.post).mockResolvedValueOnce(pin);

    await expect(pinConversationMessage("c/1", "m/1")).resolves.toBe(pin);
    await unpinConversationMessage("c/1", "m/1");

    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/conversations/c%2F1/messages/m%2F1/pin",
    );
    expect(apiClient.delete).toHaveBeenCalledExactlyOnceWith(
      "/conversations/c%2F1/messages/m%2F1/pin",
    );
  });
});
