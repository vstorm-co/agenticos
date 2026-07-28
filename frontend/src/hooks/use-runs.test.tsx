import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApprovals, useRuns, useSpend } from "./use-runs";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRuns", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the whole organization by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", undefined);
  });

  it("narrows to one agent when asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", { params: { agent_id: "a1" } });
  });
});

describe("useApprovals", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists what is waiting on a person", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "ap1", tool_id: "send_email", tool_args: { to: "a@b.c" } }],
      total: 1,
    });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.approvals).toHaveLength(1);
  });

  it("sends the decision and an optional note", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "rejected" });

    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({
      id: "ap1",
      approved: false,
      note: "wrong customer",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap1", {
      approved: false,
      note: "wrong customer",
    });
  });
});

describe("useSpend", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for the requested window", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      period_days: 7,
      month_to_date_usd: "1.23",
      by_agent: [],
    });
    const { result } = renderHook(() => useSpend(7), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/spend", { params: { days: "7" } });
    expect(result.current.spend?.month_to_date_usd).toBe("1.23");
  });
});
