import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useAdminOrganizations,
  useAdminRatingsSummary,
  useAdminStats,
  useRecentConversations,
  useRecentFailures,
  useSharedWithMeCounts,
  useSyncSources,
  useSystemHealth,
} from "./use-dashboard-data";
import { apiClient } from "@/lib/api-client";
import { listSyncSources } from "@/lib/rag-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));
vi.mock("@/lib/rag-api", () => ({
  listSyncSources: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PERIOD = { from: "2026-07-06", to: "2026-08-04" };

describe("useRecentFailures", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for exactly the statuses that mean trouble", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "r1" }], total: 1 });
    const { result } = renderHook(() => useRecentFailures(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: { status: "failed,budget_exceeded", limit: "5" },
    });
    expect(result.current.failures).toHaveLength(1);
    expect(result.current.total).toBe(1);
  });

  it("fetches nothing when the gate said no", () => {
    renderHook(() => useRecentFailures(5, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useSyncSources", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the sources with their freshness", async () => {
    vi.mocked(listSyncSources).mockResolvedValue({
      items: [{ id: "s1", name: "Drive", last_sync_status: "failed" }],
      total: 1,
    } as never);
    const { result } = renderHook(() => useSyncSources(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.sources).toHaveLength(1);
  });

  it("fetches nothing when disabled", () => {
    renderHook(() => useSyncSources({ enabled: false }), { wrapper });

    expect(listSyncSources).not.toHaveBeenCalled();
  });
});

describe("useRecentConversations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for the newest few", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "c1" }] });
    const { result } = renderHook(() => useRecentConversations(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/conversations", { params: { limit: "4" } });
    expect(result.current.conversations).toHaveLength(1);
  });

  it("fetches nothing when disabled", () => {
    renderHook(() => useRecentConversations(4, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useSharedWithMeCounts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads three totals under the shared_with_me filter, in one query", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/agents") return { items: [], total: 4 };
      if (path === "/kb") return { items: [{ id: "k1" }, { id: "k2" }, { id: "k3" }] };
      return { items: [], total: 6 };
    });
    const { result } = renderHook(() => useSharedWithMeCounts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.counts).toEqual({ agents: 4, collections: 3, skills: 6 });
    expect(apiClient.get).toHaveBeenCalledWith("/agents", {
      params: { shared_with_me: "true", limit: "1" },
    });
    expect(apiClient.get).toHaveBeenCalledWith("/kb", { params: { shared_with_me: "true" } });
    expect(apiClient.get).toHaveBeenCalledWith("/skills", {
      params: { shared_with_me: "true", limit: "1" },
    });
  });

  it("is one card and one failure, not three", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useSharedWithMeCounts(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.counts).toBeNull();
  });

  it("fetches nothing when disabled", () => {
    renderHook(() => useSharedWithMeCounts({ enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("the deployment strip's hooks", () => {
  beforeEach(() => vi.clearAllMocks());

  it("useAdminStats reads the platform counts", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_organizations: 12 });
    const { result } = renderHook(() => useAdminStats(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/stats");
    expect(result.current.stats).toEqual({ total_organizations: 12 });
  });

  it("useSystemHealth reads the probes", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ checked_at: "now", checks: [] });
    const { result } = renderHook(() => useSystemHealth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/system");
    expect(result.current.health?.checks).toEqual([]);
  });

  it("useAdminOrganizations reads the largest organizations", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "o1" }] });
    const { result } = renderHook(() => useAdminOrganizations(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/organizations", {
      params: { limit: "5" },
    });
    expect(result.current.organizations).toHaveLength(1);
  });

  it("useAdminRatingsSummary reads the deployment-wide split for the period", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ total_ratings: 1204 });
    const { result } = renderHook(() => useAdminRatingsSummary(PERIOD), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/ratings/summary", {
      params: { from: PERIOD.from, to: PERIOD.to },
    });
    expect(result.current.summary).toEqual({ total_ratings: 1204 });
  });

  it("useAdminRatingsSummary asks again when the period changes", async () => {
    // The window is the card's whole question, so it has to be in the query
    // key: without it a second period is answered from the first one's cache
    // and the chart never moves.
    vi.mocked(apiClient.get).mockResolvedValue({ total_ratings: 1 });
    const { rerender } = renderHook(({ period }) => useAdminRatingsSummary(period), {
      wrapper,
      initialProps: { period: PERIOD },
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    rerender({ period: { from: "2026-06-01", to: "2026-06-30" } });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(apiClient.get).toHaveBeenLastCalledWith("/admin/ratings/summary", {
      params: { from: "2026-06-01", to: "2026-06-30" },
    });
  });

  it("none of them fetch for a caller who is not the app admin", () => {
    renderHook(
      () => {
        useAdminStats({ enabled: false });
        useSystemHealth({ enabled: false });
        useAdminOrganizations(5, { enabled: false });
        useAdminRatingsSummary(PERIOD, { enabled: false });
      },
      { wrapper },
    );

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
