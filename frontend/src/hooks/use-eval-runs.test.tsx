import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ESTIMATE, attempt, evalCase, evalRun } from "@/test-utils/eval-runs";
import {
  isLive,
  useEvalCases,
  useEvalComparison,
  useDatasetEvalRuns,
  useDraftEvalRuns,
  useEvalArmSpec,
  useEvalRun,
  useEvalRuns,
  useEveryAgent,
  useEveryDataset,
  useRecentEvalRuns,
  useRescoreRun,
  useRunsADataset,
  useSendToReview,
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

  it("reads nothing until there is an agent", () => {
    const { result } = renderHook(() => useEvalRuns(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.runs).toEqual([]);
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
      () =>
        useEvalCases("run-1", {
          arm: "a1",
          outcome: "failed",
          tag: "refunds",
          caseIds: ["c1", "c2"],
          live: true,
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.total).toBe(7));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/eval-runs/run-1/cases?skip=0&limit=50&arm_id=a1&outcome=failed&tag=refunds&case_id=c1&case_id=c2",
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

describe("useEvalComparison while the run is live", () => {
  it("reads the verdict again until the run finishes, so it does not freeze early", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(apiClient.get)
        .mockResolvedValueOnce({ verdict: "no_difference" })
        .mockResolvedValue({ verdict: "worse" });
      const { result, rerender } = renderHook(({ live }) => useEvalComparison("run-1", { live }), {
        wrapper,
        initialProps: { live: true },
      });
      await waitFor(() => expect(result.current.comparison?.verdict).toBe("no_difference"));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_000);
      });
      await waitFor(() => expect(result.current.comparison?.verdict).toBe("worse"));

      // Finished: no more reads.
      rerender({ live: false });
      const reads = vi.mocked(apiClient.get).mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(vi.mocked(apiClient.get).mock.calls.length).toBe(reads);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("useRescoreRun", () => {
  it("grades the scores again ten a request, and reads the runs afresh even when one fails", async () => {
    const ids = Array.from({ length: 12 }, (_, n) => `s${n}`);
    vi.mocked(apiClient.post)
      .mockResolvedValueOnce({ rescored: ids.slice(0, 10).map((id) => ({ id })), kept: [] })
      .mockResolvedValueOnce({ rescored: [{ id: "s10" }], kept: ["s11"] });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRescoreRun("ds-1"), { wrapper });

    let graded: unknown;
    await act(async () => {
      graded = await result.current.mutateAsync(ids);
    });

    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/datasets/ds-1/scores/rescore", {
      score_ids: ["s10", "s11"],
    });
    expect(graded).toBe(11);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-runs"] });

    invalidate.mockClear();
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("judge down"));
    await act(async () => {
      await result.current.mutateAsync(["s1"]).catch(() => undefined);
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-runs"] });
  });
});

describe("useSendToReview", () => {
  it("reads every failed first answer of a side, page by page, and sends their scores", async () => {
    const failed = (id: string, score: string | null) =>
      evalCase({
        case_id: id,
        attempts: [
          attempt({ score: score === null ? null : ({ id: score } as never) }),
          attempt({ id: `${id}-rerun`, attempt: 1, score: { id: `${score}-r` } as never }),
          attempt({ id: `${id}-other`, arm_id: "arm-2", score: { id: `${score}-o` } as never }),
        ],
      });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [failed("c1", "s1"), failed("c2", null)], total: 101 })
      .mockResolvedValueOnce({ items: [failed("c3", "s3")], total: 101 });
    vi.mocked(apiClient.post).mockResolvedValue({ queued: 2, replaced: 1, already: 0 });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSendToReview("run-1", "ds-1"), { wrapper });

    let sent: unknown;
    await act(async () => {
      sent = await result.current.mutateAsync("arm-1");
    });

    expect(apiClient.get).toHaveBeenNthCalledWith(
      2,
      "/eval-runs/run-1/cases?outcome=failed&arm_id=arm-1&skip=100&limit=100",
    );
    expect(apiClient.post).toHaveBeenCalledWith("/datasets/ds-1/scores/review", {
      score_ids: ["s1", "s3"],
    });
    expect(sent).toEqual({ queued: 2, replaced: 1, already: 0 });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["datasets", "review-queue"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["eval-runs", "run-1"] });
  });

  it("sends nothing when no failed answer was scored", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ items: [], total: 0 });
    const { result } = renderHook(() => useSendToReview("run-1", "ds-1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("arm-1");
    });
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe("useEveryAgent", () => {
  it("reads every page of the agents, not the first alone", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: "a1" }], total: 101 })
      .mockResolvedValueOnce({ items: [{ id: "a2" }], total: 101 });
    const { result } = renderHook(() => useEveryAgent(), { wrapper });

    await waitFor(() => expect(result.current.agents).toHaveLength(2));
    expect(apiClient.get).toHaveBeenLastCalledWith("/agents", {
      params: { skip: "100", limit: "100" },
    });
  });
});

describe("useEveryDataset", () => {
  it("reads every page of the datasets by name, not the first alone", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: "d1" }], total: 101 })
      .mockResolvedValueOnce({ items: [{ id: "d2" }], total: 101 });
    const { result } = renderHook(() => useEveryDataset(), { wrapper });

    await waitFor(() => expect(result.current.datasets).toHaveLength(2));
    expect(apiClient.get).toHaveBeenLastCalledWith("/datasets", {
      params: { sort: "name", skip: "100", limit: "100" },
    });
  });
});

describe("useRunsADataset", () => {
  it("asks for one runnable dataset and answers from the total", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ items: [{ id: "d1" }], total: 3 });
    const { result } = renderHook(() => useRunsADataset(), { wrapper });

    await waitFor(() => expect(result.current).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?runnable=true&limit=1");
  });

  it("answers no, and asks nothing, while it is not needed", () => {
    const { result } = renderHook(() => useRunsADataset({ enabled: false }), { wrapper });

    expect(result.current).toBe(false);
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useEvalArmSpec", () => {
  it("reads the spec a side ran, and nothing until one is named", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ name: "Support" });
    const { result } = renderHook(() => useEvalArmSpec("run-1", "arm-1"), { wrapper });
    await waitFor(() => expect(result.current.spec).toEqual({ name: "Support" }));
    expect(apiClient.get).toHaveBeenCalledWith("/eval-runs/run-1/arms/arm-1/spec");

    vi.mocked(apiClient.get).mockClear();
    renderHook(() => useEvalArmSpec(null, null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useDatasetEvalRuns", () => {
  it("lists a dataset's runs, and polls only while one is live", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useDatasetEvalRuns("ds-1", { skip: 100 }), { wrapper });
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
    expect(result.current.total).toBe(1);
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/ds-1/eval-runs?skip=100&limit=100");

    const { query, next } = polling();
    expect(next()).toBe(false);
    query.setData({ items: [evalRun({ status: "queued" })], total: 1 });
    expect(next()).toBe(3_000);
    query.setData(undefined);
    expect(next()).toBe(false);
  });
});

describe("useDraftEvalRuns", () => {
  it("reads the latest run of the draft as it stands, and nothing when held back", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useDraftEvalRuns("agent-1"), { wrapper });
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/eval-runs?draft=current&limit=1");

    vi.mocked(apiClient.get).mockClear();
    const held = renderHook(() => useDraftEvalRuns("agent-2", { enabled: false }), { wrapper });
    const none = renderHook(() => useDraftEvalRuns(null), { wrapper });
    expect(held.result.current.runs).toEqual([]);
    expect(none.result.current.runs).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useRecentEvalRuns", () => {
  it("polls only while one of the runs is live", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useRecentEvalRuns(3), { wrapper });
    await waitFor(() => expect(result.current.runs).toHaveLength(1));

    const { query, next } = polling();
    expect(next()).toBe(false);
    query.setData({ items: [evalRun({ status: "running" })], total: 1 });
    expect(next()).toBe(3_000);
    query.setData(undefined);
    expect(next()).toBe(false);
  });

  it("reads the organization's latest runs, and nothing when held back", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 1 });
    const { result } = renderHook(() => useRecentEvalRuns(3), { wrapper });
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/eval-runs/recent?skip=0&limit=3");

    vi.mocked(apiClient.get).mockClear();
    const held = renderHook(() => useRecentEvalRuns(undefined, { enabled: false }), { wrapper });
    expect(held.result.current.runs).toEqual([]);
    expect(held.result.current.total).toBe(0);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads a later page, and says how many there are in all", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalRun()], total: 41 });
    const { result } = renderHook(() => useRecentEvalRuns(20, { skip: 40 }), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(41));
    expect(apiClient.get).toHaveBeenCalledWith("/eval-runs/recent?skip=40&limit=20");
  });
});
