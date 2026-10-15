import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCreateJudge,
  useJudgeAgreement,
  useNoteToCriterion,
  useReviewQueue,
  useScoreRun,
  useScores,
  useSetScoring,
} from "./use-scoring";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { caseScore } from "@/test-utils/scores";
import type { Dataset } from "@/types/datasets";
import type { DatasetScoring } from "@/types/scoring";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
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

describe("useScores rescore", () => {
  it("scores answers again ten a request, gathering what each request changed", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const ids = Array.from({ length: 12 }, (_, at) => `s${at}`);
    vi.mocked(apiClient.post)
      .mockResolvedValueOnce({ rescored: [{ id: "s0" }], kept: ["s1"] })
      .mockResolvedValueOnce({ rescored: [{ id: "s10" }], kept: [] });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useScores("d1"), { wrapper });

    const done = await result.current.rescore.mutateAsync(ids);

    expect(apiClient.post).toHaveBeenNthCalledWith(1, "/datasets/d1/scores/rescore", {
      score_ids: ids.slice(0, 10),
    });
    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/datasets/d1/scores/rescore", {
      score_ids: ["s10", "s11"],
    });
    expect(done).toEqual({ rescored: [{ id: "s0" }, { id: "s10" }], kept: ["s1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allScores("d1") });
  });

  it("refreshes what an earlier request changed when a later one fails", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Gone"));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useScores("d1"), { wrapper });

    await expect(result.current.rescore.mutateAsync(["s1"])).rejects.toThrow("Gone");

    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.allReviewQueue() });
  });
});

describe("useNoteToCriterion", () => {
  const dataset = {
    id: "d1",
    scoring: {
      ...DEFAULT_SCORING,
      judge: {
        ...DEFAULT_SCORING.judge,
        criteria: [{ name: "Must cite the policy", description: "x", required: true }],
      },
    },
  } as Dataset;
  const score = caseScore({ case_id: "c1", human_note: "  Must cite the policy  " });

  it("adds the note to the newest revision's checks as a judge criterion", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ checks: [{ type: "contains", value: "30" }] });
    vi.mocked(apiClient.patch).mockResolvedValue({});
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useNoteToCriterion(dataset), { wrapper });

    await result.current.mutateAsync({ score, target: "case" });

    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/cases/c1");
    expect(apiClient.patch).toHaveBeenCalledWith("/datasets/d1/cases/c1", {
      checks: [
        { type: "contains", value: "30" },
        { type: "judge", criterion: "Must cite the policy" },
      ],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.datasets.all() });
  });

  it("adds the note to the rubric under a name of its own, and switches the judge on", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({});
    const { result } = renderHook(() => useNoteToCriterion(dataset), { wrapper });

    await result.current.mutateAsync({
      score: caseScore({ human_note: null }),
      target: "dataset",
    });
    await result.current.mutateAsync({ score, target: "dataset" });

    const sent = vi.mocked(apiClient.put).mock.calls.at(-1)![1] as DatasetScoring;
    expect(sent.judge.enabled).toBe(true);
    expect(sent.judge.criteria.at(-1)).toEqual({
      name: "Must cite the policy 2",
      description: "Must cite the policy",
      required: true,
    });
  });
});

describe("useJudgeAgreement", () => {
  it("reads how often people agreed with one judge", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ agreed: 7, decided: 10 });
    const { result } = renderHook(() => useJudgeAgreement("j1"), { wrapper });

    await waitFor(() => expect(result.current.agreement).toEqual({ agreed: 7, decided: 10 }));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/judge-agreement?judge=j1");
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
