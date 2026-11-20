import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { createConversationSideThread, listConversationForks } from "./conversation-forks-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

beforeEach(() => vi.resetAllMocks());

describe("personal side thread transport", () => {
  it("lists a bounded page under the source conversation", async () => {
    const page = { items: [], total: 0 };
    vi.mocked(apiClient.get).mockResolvedValueOnce(page);

    await expect(
      listConversationForks("source/one", "answer-a", { skip: 10, limit: 25 }),
    ).resolves.toBe(page);

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith("/conversations/source%2Fone/forks", {
      params: { message_id: "answer-a", skip: "10", limit: "25" },
    });
  });

  it("creates a fork and leaves selection and URL to the caller", async () => {
    const fork = { id: "child", forked_from: { conversation_id: "source", message_id: "answer" } };
    vi.mocked(apiClient.post).mockResolvedValueOnce(fork);

    await expect(createConversationSideThread("source", "answer")).resolves.toBe(fork);

    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/conversations/source/fork", {
      message_id: "answer",
    });
  });
});
