import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  GENERATION_POLL_MS,
  useCaseGenerations,
  useCaseProposals,
  useGenerateCases,
} from "./use-case-generation";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const REQUEST = { agent_id: "a1", sources: ["knowledge" as const], count: 20 };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useCaseGenerations", () => {
  it("asks nothing of a reader who may not edit the dataset", () => {
    const { result } = renderHook(() => useCaseGenerations("d1", { enabled: false }), {
      wrapper,
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.generations).toEqual([]);
  });

  it("asks again while a generation runs, and stops once none does", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: "g1", status: "running" }] })
      .mockResolvedValue({ items: [{ id: "g1", status: "ready" }] });
    const { result } = renderHook(() => useCaseGenerations("d1", { enabled: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.generations[0]?.status).toBe("running"));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/generations");

    await act(() => vi.advanceTimersByTimeAsync(GENERATION_POLL_MS));
    await waitFor(() => expect(result.current.generations[0]?.status).toBe("ready"));
    await act(() => vi.advanceTimersByTimeAsync(GENERATION_POLL_MS * 2));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});

describe("useCaseProposals", () => {
  it("reads one page of drafts", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "p1" }], total: 30 });
    const { result } = renderHook(
      () => useCaseProposals("d1", { enabled: true, skip: 20, limit: 20 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.total).toBe(30));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/proposals", {
      params: { skip: "20", limit: "20" },
    });
    expect(result.current.proposals).toEqual([{ id: "p1" }]);
  });

  it("reads an empty answer as nothing waiting", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useCaseProposals("d1", { enabled: true }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(result.current.proposals).toEqual([]);
    expect(result.current.total).toBe(0);
  });

  it("accepts drafts as one version and says which", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ number: 4, changed_cases: 2 });
    const { result } = renderHook(() => useCaseProposals("d1", { enabled: true }), { wrapper });

    await act(() => result.current.accept.mutateAsync([{ id: "p1" }, { id: "p2" }]));

    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/proposals/accept", {
      items: [{ id: "p1" }, { id: "p2" }],
    });
    expect(toastSuccess).toHaveBeenCalledWith("2 cases added as version 4");
  });

  it("dismisses drafts and says a refusal out loud", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useCaseProposals("d1", { enabled: true }), { wrapper });

    await act(() => result.current.dismiss.mutateAsync(["p1"]));
    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/proposals/dismiss", {
      ids: ["p1"],
    });
    expect(toastSuccess).toHaveBeenCalledWith("1 proposed case dismissed");

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("gone"));
    await act(async () => {
      await result.current.dismiss.mutateAsync(["p1"]).catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useGenerateCases", () => {
  it("estimates and starts the same request", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "g1" });
    const { result } = renderHook(() => useGenerateCases("d1"), { wrapper });

    await act(() => result.current.estimate.mutateAsync(REQUEST));
    await act(() => result.current.start.mutateAsync(REQUEST));

    expect(apiClient.post).toHaveBeenNthCalledWith(1, "/datasets/d1/generations/estimate", REQUEST);
    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/datasets/d1/generations", REQUEST);
  });
});
