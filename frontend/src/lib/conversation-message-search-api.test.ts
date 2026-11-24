import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { searchConversationMessages } from "./conversation-message-search-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

beforeEach(() => vi.resetAllMocks());

describe("conversation message search transport", () => {
  it("sends a trimmed literal query to the bounded message-search route", async () => {
    const hits = [{ conversation_id: "c-1", message_id: "m-1" }];
    vi.mocked(apiClient.get).mockResolvedValueOnce(hits);

    await expect(searchConversationMessages("  renewal -paused ")).resolves.toBe(hits);

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith("/conversations/search/messages", {
      params: { query: "renewal -paused" },
    });
  });
});
