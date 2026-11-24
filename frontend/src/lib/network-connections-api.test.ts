import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  listNetworkPeers,
  pauseNetworkConnection,
  refreshNetworkConnection,
  revokeNetworkConnection,
} from "./network-connections-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("network connection actions", () => {
  it("lists peers with the caller's abort signal", async () => {
    const signal = new AbortController().signal;
    const peers = { items: [], observed_at: null };
    vi.mocked(apiClient.get).mockResolvedValue(peers);

    await expect(listNetworkPeers("conn/1", signal)).resolves.toEqual(peers);

    expect(apiClient.get).toHaveBeenCalledWith("/network-connections/conn%2F1/peers", { signal });
  });

  it.each([
    ["refresh", refreshNetworkConnection],
    ["pause", pauseNetworkConnection],
    ["revoke", revokeNetworkConnection],
  ])("posts the %s action to the encoded connection route", async (action, run) => {
    const connection = { id: "conn/1" };
    vi.mocked(apiClient.post).mockResolvedValue(connection);

    await expect(run("conn/1")).resolves.toEqual(connection);

    expect(apiClient.post).toHaveBeenCalledWith(`/network-connections/conn%2F1/${action}`);
  });
});
