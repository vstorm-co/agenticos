import { describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { listConversationOutcomes, settleOutcome } from "./outcomes-api";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

describe("outcomes api", () => {
  it("lists the open outcomes of one chat", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "o-1" }] });

    await expect(listConversationOutcomes("c-1")).resolves.toEqual([{ id: "o-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/outcomes?conversation_id=c-1");
  });

  it("settles one outcome and says where it was done", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "o-1", status: "resolved" });

    await settleOutcome("o-1", "resolve", "chat");

    expect(apiClient.post).toHaveBeenCalledWith("/outcomes/o-1/settle", {
      action: "resolve",
      via: "chat",
    });
  });
});
