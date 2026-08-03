import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./sandbox-connections-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/**
 * The client for where an organization's sandboxes run.
 *
 * What is worth asserting is the addressing. The policy call in particular has to
 * go through our own API rather than at the sandbox service: reaching that
 * service needs a token that authorises running commands on the host, and a
 * browser must never hold one.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "c-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "c-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "c-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the sandbox connections client", () => {
  it("unwraps the list, because no caller wants the envelope", async () => {
    await expect(api.listSandboxConnections()).resolves.toEqual([{ id: "c-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-connections");
  });

  it("registers a connection with a reference to its credential, never a value", async () => {
    await api.createSandboxConnection({
      name: "Local Docker",
      kind: "docker",
      base_url: "http://sandboxd:8080",
      secret_id: "s-1",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/sandbox-connections", {
      name: "Local Docker",
      kind: "docker",
      base_url: "http://sandboxd:8080",
      secret_id: "s-1",
    });
  });

  it("addresses update and delete by id", async () => {
    await api.updateSandboxConnection("c-1", { is_default: true });
    expect(apiClient.patch).toHaveBeenCalledWith("/sandbox-connections/c-1", { is_default: true });

    await api.deleteSandboxConnection("c-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/sandbox-connections/c-1");
  });

  it("asks for the sessions without sampling usage unless told to", async () => {
    // The service pays a daemon round trip per sandbox to sample it.
    vi.mocked(apiClient.get).mockResolvedValue({ sessions: [] });

    await api.listSandboxSessions("c-1");
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-connections/c-1/sessions?usage=false");

    await api.listSandboxSessions("c-1", true);
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-connections/c-1/sessions?usage=true");
  });

  it("reads an activity log from the sequence it already holds", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ events: [], latest_seq: 0 });

    await api.readSandboxEvents("c-1", "xc-1");
    expect(apiClient.get).toHaveBeenCalledWith(
      "/sandbox-connections/c-1/sessions/xc-1/events?after=0",
    );

    await api.readSandboxEvents("c-1", "xc-1", 7);
    expect(apiClient.get).toHaveBeenCalledWith(
      "/sandbox-connections/c-1/sessions/xc-1/events?after=7",
    );
  });

  it("reads the policy through our own API rather than the sandbox service", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ kind: "docker", runtimes: [] });

    await expect(api.readSandboxPolicy("c-1")).resolves.toEqual({ kind: "docker", runtimes: [] });
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-connections/c-1/policy");
  });

  it("asks whether this deployment runs a service of its own", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      url: "http://sandboxd:8080",
      token_available: true,
      registered_connection_id: null,
    });

    await expect(api.readLocalSandboxService()).resolves.toMatchObject({
      url: "http://sandboxd:8080",
    });
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-connections/local");
  });

  it("stores the local token without sending one", async () => {
    // The value is in the backend's own environment. A request carrying it would
    // mean the browser had it, which is the thing this avoids.
    vi.mocked(apiClient.post).mockResolvedValue({ secret_id: "s-1", name: "t", hint: "4242" });

    await api.storeLocalSandboxCredential();

    expect(apiClient.post).toHaveBeenCalledWith("/sandbox-connections/local/credential");
  });

  it("probes an unsaved address through our own API, key by reference", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ kind: "docker", runtimes: [] });

    await api.probeSandboxService("http://sandboxd:8080", "s-1");

    expect(apiClient.post).toHaveBeenCalledWith("/sandbox-connections/probe", {
      base_url: "http://sandboxd:8080",
      secret_id: "s-1",
    });
  });
});
