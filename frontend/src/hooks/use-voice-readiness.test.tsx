import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { voiceReadiness } from "@/lib/voice-api";
import type { VoiceReadiness } from "@/types/voice";
import { useVoiceReadiness } from "./use-voice-readiness";

vi.mock("@/lib/voice-api", () => ({ voiceReadiness: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const READY: VoiceReadiness = {
  available: true,
  unavailable: null,
  transport: "webrtc",
  provider: "openai",
  model: "gpt-realtime",
  cap_seconds: 600,
  minutes_left: 540,
};

describe("useVoiceReadiness", () => {
  it("asks nothing without an agent", () => {
    const { result } = renderHook(() => useVoiceReadiness(null), { wrapper });
    expect(result.current).toEqual({ readiness: null, failed: false });
    expect(voiceReadiness).not.toHaveBeenCalled();
  });

  it("answers with the agent's readiness", async () => {
    vi.mocked(voiceReadiness).mockResolvedValue(READY);
    const { result } = renderHook(() => useVoiceReadiness("a1"), { wrapper });
    await waitFor(() => expect(result.current.readiness).toEqual(READY));
    expect(result.current.failed).toBe(false);
    expect(voiceReadiness).toHaveBeenCalledWith("a1", "web");
  });

  it("asks about the embed surface when the embed form does", async () => {
    vi.mocked(voiceReadiness).mockResolvedValue(READY);
    const { result } = renderHook(() => useVoiceReadiness("a1", "embed"), { wrapper });
    await waitFor(() => expect(result.current.readiness).toEqual(READY));
    expect(voiceReadiness).toHaveBeenCalledWith("a1", "embed");
  });

  it("says when the read failed rather than pretending a call is off", async () => {
    vi.mocked(voiceReadiness).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useVoiceReadiness("a1"), { wrapper });
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.readiness).toBeNull();
  });
});
