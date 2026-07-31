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

  it("fetches nothing for a caller that is not ready to ask", () => {
    // The Activity tab mounts before the organization is resolved; a request sent
    // then reads another organization's runs or none at all.
    renderHook(() => useRuns("a1", { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure rather than an empty history", async () => {
    // An empty list and a refused read look identical on the page, and only one
    // of them is worth showing an error for.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Missing required permission"));
    const { result } = renderHook(() => useRuns(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.runs).toEqual([]);
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

  it("says which way a decision went", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "approved" });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    expect(toast.success).toHaveBeenCalledWith("Approved");
  });

  it("surfaces a refused second decision instead of leaving the queue silent", async () => {
    // The server refuses a decision on an approval somebody else already decided,
    // which is exactly what two people opening the queue at once produces.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Already decided"));
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.decide.mutateAsync({ id: "ap1", approved: true })).rejects.toThrow(
      "Already decided",
    );

    expect(toast.error).toHaveBeenCalledWith("Already decided");
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
