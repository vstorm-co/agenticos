import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { realtimeModels, voiceReadiness, voiceUsage } from "./voice-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

describe("voice api", () => {
  beforeEach(() => vi.mocked(apiClient.get).mockReset());

  it("reads an agent's readiness by its id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ available: true });
    await voiceReadiness("a1");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/voice");
  });

  it("asks about the embed surface for a widget or a hosted page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ available: true });
    await voiceReadiness("a1", "embed");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/voice?surface=embed");
  });

  it("reads the realtime catalog", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await realtimeModels();
    expect(apiClient.get).toHaveBeenCalledWith("/providers/realtime-models");
  });

  it("reads the call minutes for a window of instants", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({});
    await voiceUsage("2026-09-01T00:00:00.000Z", "2026-09-07T23:59:59.999Z");
    expect(apiClient.get).toHaveBeenCalledWith(
      "/voice/usage?start=2026-09-01T00%3A00%3A00.000Z&end=2026-09-07T23%3A59%3A59.999Z",
    );
  });
});
