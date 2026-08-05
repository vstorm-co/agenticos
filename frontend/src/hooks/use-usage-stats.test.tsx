import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRatingsSummary, useUsageStats, useVersionUsage } from "./use-usage-stats";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PERIOD = { from: "2026-07-06", to: "2026-08-04" };

describe("useUsageStats", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for the window at org scope by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_runs: 3 });
    const { result } = renderHook(() => useUsageStats(PERIOD), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/stats/usage", {
      params: { from: PERIOD.from, to: PERIOD.to, scope: "org" },
    });
    expect(result.current.usage).toEqual({ total_runs: 3 });
  });

  it("asks for the caller's own rows when scoped so", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_runs: 1 });
    const { result } = renderHook(() => useUsageStats(PERIOD, { scope: "own" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/stats/usage", {
      params: { from: PERIOD.from, to: PERIOD.to, scope: "own" },
    });
  });

  it("fetches nothing when the widget's gate said no", () => {
    renderHook(() => useUsageStats(PERIOD, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure rather than empty numbers", async () => {
    // Zero runs and a refused read look identical on a chart; only one of
    // them deserves the error card.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Insufficient permissions"));
    const { result } = renderHook(() => useUsageStats(PERIOD), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.usage).toBeNull();
  });
});

describe("useVersionUsage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the version question for one agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ by_version: [{ version: 3, runs: 10 }] });
    const { result } = renderHook(() => useVersionUsage("agent-1", PERIOD), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/stats/usage", {
      params: {
        from: PERIOD.from,
        to: PERIOD.to,
        group_by: "version",
        agent_id: "agent-1",
      },
    });
    expect(result.current.byVersion).toEqual([{ version: 3, runs: 10 }]);
  });

  it("asks nothing while no agent qualifies", () => {
    renderHook(() => useVersionUsage(null, PERIOD), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("stays quiet when disabled even with an agent", () => {
    renderHook(() => useVersionUsage("agent-1", PERIOD, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useRatingsSummary", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the organization's answers by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_ratings: 214, like_count: 195 });
    const { result } = renderHook(() => useRatingsSummary(PERIOD), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/ratings/summary", {
      params: { from: PERIOD.from, to: PERIOD.to, scope: "org" },
    });
    expect(result.current.ratings).toEqual({ total_ratings: 214, like_count: 195 });
  });

  it("narrows to the caller's own conversations when asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_ratings: 37 });
    const { result } = renderHook(() => useRatingsSummary(PERIOD, { scope: "own" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/ratings/summary", {
      params: { from: PERIOD.from, to: PERIOD.to, scope: "own" },
    });
  });

  it("fetches nothing when disabled", () => {
    renderHook(() => useRatingsSummary(PERIOD, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure with no summary", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useRatingsSummary(PERIOD), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.ratings).toBeNull();
  });
});
