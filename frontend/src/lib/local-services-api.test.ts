import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./local-services-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/**
 * The client for the servers an organization's collections may reach on the
 * deployment's own network. What is worth asserting is the addressing and the
 * shape of what leaves: an address and a name, never a credential - a keyless
 * endpoint is the reason a row exists.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "ls-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "ls-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "ls-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the local services client", () => {
  it("unwraps the list, because no caller wants the envelope", async () => {
    await expect(api.listLocalServices()).resolves.toEqual([{ id: "ls-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/local-services");
  });

  it("registers a server as an address, with the kind's provider", async () => {
    await api.createLocalService({
      name: "GPU box",
      kind: "embedding",
      provider: api.LOCAL_SERVICE_PROVIDERS.embedding,
      base_url: "http://ollama:11434/v1",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/local-services", {
      name: "GPU box",
      kind: "embedding",
      provider: "ollama",
      base_url: "http://ollama:11434/v1",
    });
  });

  it("addresses update and delete by id", async () => {
    await api.updateLocalService("ls-1", { is_active: false });
    expect(apiClient.patch).toHaveBeenCalledWith("/local-services/ls-1", { is_active: false });

    await api.deleteLocalService("ls-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/local-services/ls-1");
  });

  it("derives one provider per kind, so a form never asks for it", () => {
    expect(api.LOCAL_SERVICE_PROVIDERS).toEqual({ embedding: "ollama", ocr: "liteparse" });
  });
});
