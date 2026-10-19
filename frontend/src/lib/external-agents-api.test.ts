import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./external-agents-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "ea-1" }] });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "ea-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the remote agents client", () => {
  it("unwraps the list", async () => {
    await expect(api.listExternalAgents()).resolves.toEqual([{ id: "ea-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/external-agents");
  });

  it("registers by the card's address, with the key it should send", async () => {
    await api.registerExternalAgent({ card_url: "https://agents.example.com", secret_id: "s-1" });
    expect(apiClient.post).toHaveBeenCalledWith("/external-agents", {
      card_url: "https://agents.example.com",
      secret_id: "s-1",
    });
  });

  it("refreshes and removes one by its id", async () => {
    await api.refreshExternalAgent("ea-1");
    expect(apiClient.post).toHaveBeenCalledWith("/external-agents/ea-1/refresh", {});
    await api.deleteExternalAgent("ea-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/external-agents/ea-1");
  });
});
