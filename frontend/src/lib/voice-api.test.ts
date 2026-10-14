import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { realtimeModels, voiceReadiness } from "./voice-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

describe("voice api", () => {
  beforeEach(() => vi.mocked(apiClient.get).mockReset());

  it("reads an agent's readiness by its id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ available: true });
    await voiceReadiness("a1");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/voice");
  });

  it("reads the realtime catalog", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await realtimeModels();
    expect(apiClient.get).toHaveBeenCalledWith("/providers/realtime-models");
  });
});
