import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ESTIMATE, evalRun } from "@/test-utils/eval-runs";
import {
  isLive,
  useEvalCases,
  useEvalComparison,
  useEvalRun,
  useEvalRuns,
  useRecentEvalRuns,
} from "./use-eval-runs";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

let client: QueryClient;

/** The only query mounted, and what its polling decides for its current data. */
function polling() {
  const [query] = client.getQueryCache().getAll();
  if (query === undefined) throw new Error("no query mounted");
  const { refetchInterval } = query.options as {
    refetchInterval: (current: typeof query) => number | false;
  };
  return { query, next: () => refetchInterval(query) };
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const REQUEST = {
  dataset_id: "ds-1",
  candidate: "draft" as const,
  model_profile_ids: [],
  paired_baseline: false,
  from_recordings: false,
  live_reads: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("isLive", () => {
  it("is true while a run can still answer cases", () => {
    expect(isLive("queued")).toBe(true);
    expect(isLive("running")).toBe(true);
    expect(isLive("completed")).toBe(false);
    expect(isLive("budget_exceeded")).toBe(false);
  });
});

describe("useEvalRuns", () => {
  it("lists an agent's runs, and polls only while one is live", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useEvalRuns("agent-1", { skip: 20, limit: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/eval-runs?skip=20&limit=10");
    expect(result.current.runs).toHaveLength(1);
    expect(result.current.total).toBe(1);
    const { query, next } = polling();
    expect(next()).toBe(false);
    query.setData({ items: [evalRun({ status: "running" })], total: 1 });
    expect(next()).toBe(3_000);
  });

  it("estimates without writing and starts what was estimated", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValueOnce(ESTIMATE).mockResolvedValueOnce(evalRun());
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useEvalRuns("agent-1"), { wrapper });

    await act(async () => {
      await result.current.estimate.mutateAsync(REQUEST);
    });
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/eval-runs/estimate", REQUEST);
    expect(invalidate).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.start.mutateAsync(REQUEST);
    });
    expect(apiClient.post).toHaveBeenLastCalledWith("/agents/agent-1/eval-runs", REQUEST);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-runs"] });
  });

  it("reads defaults when no page is asked for", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useEvalRuns("agent-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/eval-runs?skip=0&limit=20");
    expect(result.current.runs).toEqual([]);
  });
});

describe("useEvalRun", () => {
  it("reads one run, polls while it is live, and stops it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(evalRun({ status: "running" }));
    vi.mocked(apiClient.post).mockResolvedValue(evalRun({ status: "cancelled" }));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useEvalRun("run-1"), { wrapper });
    await waitFor(() => expect(result.current.run?.id).toBe("run-1"));

    const { query, next } = polling();
    expect(next()).toBe(3_000);
    query.setData(evalRun({ status: "completed" }));
    expect(next()).toBe(false);
    query.setData(undefined);
    expect(next()).toBe(false);

    await act(async () => {
      await result.current.cancel.mutateAsync();
    });
    expect(apiClient.post).toHaveBeenCalledWith("/eval-runs/run-1/cancel", {});
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-runs"] });
  });
});

describe("useEvalCases", () => {
  it("narrows by arm, outcome and tag only when asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 7 });
    const { result } = renderHook(
      () => useEvalCases("run-1", { arm: "a1", outcome: "failed", tag: "refunds", live: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.total).toBe(7));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/eval-runs/run-1/cases?skip=0&limit=50&arm_id=a1&outcome=failed&tag=refunds",
    );

    const plain = renderHook(() => useEvalCases("run-2"), { wrapper });
    await waitFor(() => expect(plain.result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenLastCalledWith("/eval-runs/run-2/cases?skip=0&limit=50");
    expect(plain.result.current.cases).toEqual([]);
  });
});

describe("useEvalComparison", () => {
  it("compares with the default baseline unless an arm or a run is named", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ verdict: null });
    const { result } = renderHook(() => useEvalComparison("run-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/eval-runs/run-1/comparison");

    renderHook(() => useEvalComparison("run-1", { arm: "a2", baseline: "run-0" }), { wrapper });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenLastCalledWith(
        "/eval-runs/run-1/comparison?arm_id=a2&baseline_run_id=run-0",
      ),
    );
  });
});

describe("useRecentEvalRuns", () => {
  it("reads the organization's latest runs, and nothing when held back", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useRecentEvalRuns(3), { wrapper });
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/eval-runs/recent?limit=3");

    vi.mocked(apiClient.get).mockClear();
    const held = renderHook(() => useRecentEvalRuns(undefined, { enabled: false }), { wrapper });
    expect(held.result.current.runs).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
