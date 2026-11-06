import { describe, expect, it, vi } from "vitest";

import { openPrimaryConversation } from "./primary-conversation-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { post: vi.fn() } }));

describe("openPrimaryConversation", () => {
  it("asks for the caller's conversation with the agent and returns its id", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ conversation_id: "c-1" });

    await expect(openPrimaryConversation("a-1")).resolves.toBe("c-1");
    expect(apiClient.post).toHaveBeenCalledWith("/agents/a-1/primary-conversation", {});
  });
});
