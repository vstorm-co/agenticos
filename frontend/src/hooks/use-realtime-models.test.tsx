import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { realtimeModels } from "@/lib/voice-api";
import { useRealtimeModels } from "./use-realtime-models";

vi.mock("@/lib/voice-api", () => ({ realtimeModels: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const OPENAI = {
  provider: "openai",
  name: "OpenAI",
  secret_kind: "api_key" as const,
  deployment: false,
  models: [],
};

describe("useRealtimeModels", () => {
  beforeEach(() => vi.clearAllMocks());

  it("answers with the providers that can hold a call", async () => {
    vi.mocked(realtimeModels).mockResolvedValue({ items: [OPENAI], total: 1 });
    const { result } = renderHook(() => useRealtimeModels(), { wrapper });
    await waitFor(() => expect(result.current.providers).toEqual([OPENAI]));
    expect(result.current.isError).toBe(false);
  });

  it("answers with no providers when the catalog cannot be read", async () => {
    vi.mocked(realtimeModels).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useRealtimeModels(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.providers).toEqual([]);
  });
});
