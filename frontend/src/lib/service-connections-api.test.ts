import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./service-connections-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/**
 * The client for the endpoints an organization's collections may reach. What is
 * worth asserting is the addressing and the shape of what leaves: an address, a
 * name and at most the id of a Vault key, never a credential.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "ls-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "ls-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "ls-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the service connections client", () => {
  it("unwraps the list, because no caller wants the envelope", async () => {
    await expect(api.listServiceConnections()).resolves.toEqual([{ id: "ls-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/service-connections");
  });

  it("registers a server as an address, with the kind's provider", async () => {
    await api.createServiceConnection({
      name: "GPU box",
      kind: "embedding",
      provider: "ollama",
      base_url: "http://ollama:11434/v1",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/service-connections", {
      name: "GPU box",
      kind: "embedding",
      provider: "ollama",
      base_url: "http://ollama:11434/v1",
    });
  });

  it("addresses update and delete by id", async () => {
    await api.updateServiceConnection("ls-1", { is_active: false });
    expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-1", { is_active: false });

    await api.deleteServiceConnection("ls-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/service-connections/ls-1");
  });

  it("offers each kind its API styles, and a key only to an OpenAI-compatible one", () => {
    expect(api.SERVICE_CONNECTION_STYLES).toEqual({
      embedding: ["ollama", "openai_compatible"],
      ocr: ["liteparse"],
    });
    expect([...api.KEYED_STYLES]).toEqual(["openai_compatible"]);
  });

  it("carries the key by id and the test token on an update", async () => {
    await api.createServiceConnection({
      name: "Gateway",
      kind: "embedding",
      provider: "openai_compatible",
      base_url: "https://gw.example/v1",
      secret_id: "sec-1",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/service-connections", {
      name: "Gateway",
      kind: "embedding",
      provider: "openai_compatible",
      base_url: "https://gw.example/v1",
      secret_id: "sec-1",
    });

    await api.updateServiceConnection("ls-1", { base_url: "https://b/v1", probe_token: "tok" });
    expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-1", {
      base_url: "https://b/v1",
      probe_token: "tok",
    });
  });

  it("estimates and probes a connection on its own routes", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ calls: 3, max_calls: 6, knowledge_bases: 1 });
    await expect(api.estimateConnectionProbe("ls-1")).resolves.toEqual({
      calls: 3,
      max_calls: 6,
      knowledge_bases: 1,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/service-connections/ls-1/probe/estimate");

    await api.probeConnection("ls-1", { base_url: "https://b/v1" });
    expect(apiClient.post).toHaveBeenCalledWith("/service-connections/ls-1/probe", {
      base_url: "https://b/v1",
    });
  });
});
