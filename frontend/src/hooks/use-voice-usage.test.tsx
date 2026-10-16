import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { voiceUsage } from "@/lib/voice-api";
import type { VoiceUsage } from "@/types/voice";
import { useVoiceUsage } from "./use-voice-usage";

vi.mock("@/lib/voice-api", () => ({ voiceUsage: vi.fn() }));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const RANGE = { start: "2026-09-01T00:00:00.000Z", end: "2026-09-30T23:59:59.999Z" };

const USAGE: VoiceUsage = {
  start: "2026-09-01T00:00:00Z",
  end: "2026-10-01T00:00:00Z",
  seconds: 720,
  calls: 4,
  by_agent: [],
  month_seconds: 900,
  monthly_minutes: 600,
};

describe("useVoiceUsage", () => {
  beforeEach(() => {
    vi.mocked(voiceUsage).mockReset();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  it("asks nothing for a caller who may not read runs", () => {
    const { result } = renderHook(() => useVoiceUsage(RANGE, { enabled: false }), { wrapper });
    expect(result.current.usage).toBeNull();
    expect(voiceUsage).not.toHaveBeenCalled();
  });

  it("answers with the window's minutes, and reads again on a retry", async () => {
    vi.mocked(voiceUsage).mockResolvedValue(USAGE);
    const { result } = renderHook(() => useVoiceUsage(RANGE, { enabled: true }), { wrapper });
    await waitFor(() => expect(result.current.usage).toEqual(USAGE));
    expect(voiceUsage).toHaveBeenCalledWith(RANGE.start, RANGE.end);
    act(() => result.current.refetch());
    await waitFor(() => expect(voiceUsage).toHaveBeenCalledTimes(2));
  });

  it("carries the failure rather than an empty answer", async () => {
    vi.mocked(voiceUsage).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useVoiceUsage(RANGE, { enabled: true }), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect((result.current.error as Error).message).toBe("502");
    expect(result.current.usage).toBeNull();
  });
});
