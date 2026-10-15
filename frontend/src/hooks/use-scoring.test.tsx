import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCreateJudge,
  useReviewQueue,
  useScoreRun,
  useScores,
  useSetScoring,
} from "./use-scoring";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { DEFAULT_SCORING } from "@/lib/scoring";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("useCreateJudge", () => {
  it("creates the dataset's judge, keeps the dataset and refreshes the judges", async () => {
    const dataset = { id: "d1", scoring: DEFAULT_SCORING };
    vi.mocked(apiClient.post).mockResolvedValue(dataset);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useCreateJudge("d1"), { wrapper });

    await result.current.mutateAsync({ name: "Refunds judge", instructions: "Be strict." });

    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/judge", {
      name: "Refunds judge",
      instructions: "Be strict.",
    });
    expect(client.getQueryData(qk.datasets.detail("d1"))).toEqual(dataset);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.judges() });
  });
});

describe("useSetScoring", () => {
  it("puts the whole configuration and keeps the dataset it answers with", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ id: "d1", scoring: DEFAULT_SCORING });
    const { result } = renderHook(() => useSetScoring("d1"), { wrapper });

    await result.current.mutateAsync(DEFAULT_SCORING);

    expect(apiClient.put).toHaveBeenCalledWith("/datasets/d1/scoring", DEFAULT_SCORING);
    expect(client.getQueryData(qk.datasets.detail("d1"))).toEqual({
      id: "d1",
      scoring: DEFAULT_SCORING,
    });
  });
});

describe("useScoreRun", () => {
  it("scores a run against a case and refreshes the scores and the queue", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1" });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useScoreRun(), { wrapper });

    await result.current.mutateAsync({ datasetId: "d1", caseId: "c1", runId: "r1" });

    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/cases/c1/scores", { run_id: "r1" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allScores("d1") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allReviewQueue() });
  });
});

describe("useScores", () => {
  it("asks for one case's pending scores, a page at a time", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "s1" }], total: 1 });
    const { result } = renderHook(
      () => useScores("d1", { caseId: "c1", pending: true, skip: 10, limit: 5 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.total).toBe(1));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/datasets/d1/scores?skip=10&limit=5&case_id=c1&pending=true",
    );
    expect(result.current.scores).toEqual([{ id: "s1" }]);
  });

  it("narrows by outcome, agent and tag, and takes scores out of the queue", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ removed: 2, kept: 0 });
    const { result } = renderHook(
      () => useScores("d1", { outcome: "failed", agentId: "a1", tag: "billing" }),
      { wrapper },
    );

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/datasets/d1/scores?skip=0&limit=50&outcome=failed&agent_id=a1&tag=billing",
      ),
    );
    await result.current.withdraw.mutateAsync(["s1", "s2"]);
    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/scores/review/withdraw", {
      score_ids: ["s1", "s2"],
    });
  });

  it("reads every score by default, and answers empty before the first page lands", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useScores("d1"), { wrapper });

    expect(result.current.scores).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/scores?skip=0&limit=50");
  });

  it("records a verdict and sends a score to review, refreshing both lists", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.put).mockResolvedValue({ id: "s1" });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1" });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useScores("d1"), { wrapper });

    await result.current.verdict.mutateAsync({ scoreId: "s1", passed: true, note: "ok" });
    await result.current.review.mutateAsync("s1");

    expect(apiClient.put).toHaveBeenCalledWith("/datasets/d1/scores/s1/verdict", {
      passed: true,
      note: "ok",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/scores/s1/review");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allScores("d1") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allReviewQueue() });
  });
});

describe("useReviewQueue", () => {
  it("reads the queue across datasets", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "s1" }], total: 3 });
    const { result } = renderHook(() => useReviewQueue({ limit: 5 }), { wrapper });

    await waitFor(() => expect(result.current.total).toBe(3));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/review-queue?skip=0&limit=5");
    expect(result.current.scores).toEqual([{ id: "s1" }]);
  });

  it("answers empty before the queue lands", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useReviewQueue(), { wrapper });

    expect(result.current.scores).toEqual([]);
    expect(result.current.total).toBe(0);
  });
});
