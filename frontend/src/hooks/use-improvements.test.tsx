import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useImprovement, useImprovements, useImprovementEvidence } from "./use-improvements";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
});
it("estimates without writing, starts with the confirmed limit and loads durable sessions", async () => {
  vi.mocked(apiClient.get).mockResolvedValue([{ id: "s1", status: "published" }]);
  vi.mocked(apiClient.post).mockResolvedValue({ id: "s2" });
  const { result } = renderHook(() => useImprovements("a1"), { wrapper });
  await waitFor(() => expect(result.current.sessions).toHaveLength(1));
  const invalidation = vi.spyOn(client, "invalidateQueries");
  await result.current.estimate.mutateAsync({ dataset_id: "d1", max_iterations: 3 });
  expect(invalidation).not.toHaveBeenCalled();
  await result.current.start.mutateAsync({ dataset_id: "d1", budget_usd: "0.50" });
  expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/improvements", {
    dataset_id: "d1",
    budget_usd: "0.50",
  });
  expect(invalidation).toHaveBeenCalledWith({ queryKey: ["improvements"] });
});
it("does not read a hidden session listing", () => {
  renderHook(() => useImprovements("a1", { enabled: false }), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});
it("loads a reopened session and requires the reviewed price for attribution", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "s1", status: "ready" });
  vi.mocked(apiClient.post).mockResolvedValue({});
  const { result } = renderHook(() => useImprovement("a1", "s1"), { wrapper });
  await waitFor(() => expect(result.current.session?.id).toBe("s1"));
  await result.current.estimateAttribution.mutateAsync(2);
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/rounds/2/attribution/estimate",
    {},
  );
  await result.current.attribute.mutateAsync({ number: 2, estimate: "0.02" });
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/rounds/2/attribution",
    { confirmed: true, estimate_usd: "0.02" },
  );
  await result.current.selectRound.mutateAsync(1);
  await result.current.retry.mutateAsync();
  await result.current.cancel.mutateAsync();
  await result.current.finish.mutateAsync({
    confirmed: true,
    publish: true,
    automatic_check: true,
  });
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/finish", {
    confirmed: true,
    publish: true,
    automatic_check: true,
  });
});

it("keeps draft testing separate and sends consent for the quoted draft and selected questions", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "s1", status: "ready" });
  vi.mocked(apiClient.post).mockResolvedValue({});
  const { result } = renderHook(() => useImprovement("a1", "s1"), { wrapper });
  await waitFor(() => expect(result.current.session?.id).toBe("s1"));
  const target = { topic_id: "t1", round: 1, case_ids: ["q1", "q2"] };
  const invalidation = vi.spyOn(client, "invalidateQueries");
  await result.current.estimateKnowledge.mutateAsync(target);
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/knowledge/estimate",
    target,
  );
  expect(invalidation).not.toHaveBeenCalled();
  const consent = {
    ...target,
    confirmed: true as const,
    draft_hash: "a".repeat(64),
    estimate_usd: "0.02",
  };
  await result.current.checkKnowledge.mutateAsync(consent);
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/knowledge", consent);
  expect(invalidation).toHaveBeenCalledWith({ queryKey: ["improvements"] });
});

it("separates the free preview from pinned session evidence", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], sample_limit: 20, training_failures: 0 });
  const view = renderHook<
    ReturnType<typeof useImprovementEvidence>,
    { sessionId: string | null; datasetId: string | null }
  >(
    ({ sessionId, datasetId }: { sessionId: string | null; datasetId: string | null }) =>
      useImprovementEvidence("a1", { sessionId, datasetId, live: false }),
    {
      wrapper,
      initialProps: { sessionId: null, datasetId: "d1" },
    },
  );
  await waitFor(() => expect(view.result.current.evidence?.sample_limit).toBe(20));
  expect(apiClient.get).toHaveBeenLastCalledWith("/agents/a1/improvements/preview", {
    params: { dataset_id: "d1" },
  });
  view.rerender({ sessionId: "s1", datasetId: "d2" });
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/evidence", {
      params: {},
    }),
  );
});

it("binds selected checks to their choices, complete price and candidate hash", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "s1", status: "ready" });
  const quote = { suggestions: 1, total_usd: "0.04", affordable: true, candidate_hash: "hash" };
  vi.mocked(apiClient.post).mockResolvedValue(quote);
  const { result } = renderHook(() => useImprovement("a1", "s1"), { wrapper });
  await result.current.estimateSelection.mutateAsync({ number: 1, hunkIds: ["h1"] });
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/rounds/1/selection/estimate",
    { hunk_ids: ["h1"] },
  );
  await result.current.checkSelection.mutateAsync({ number: 1, hunkIds: ["h1"], quote });
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/rounds/1/selection", {
    hunk_ids: ["h1"],
    confirmed: true,
    estimate_usd: "0.04",
    candidate_hash: "hash",
  });
});

it("requires the continuation quote and confirms discarding explicitly", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "s1", status: "ready" });
  const quote = {
    mode: "next_round" as const,
    number: 2,
    total_usd: "0.04",
    budget_usd: "1",
    affordable: true,
    candidate_hash: "hash",
  };
  vi.mocked(apiClient.post).mockResolvedValue(quote);
  const { result } = renderHook(() => useImprovement("a1", "s1"), { wrapper });
  await result.current.estimateContinuation.mutateAsync("1");
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/continue/estimate", {
    budget_usd: "1",
  });
  await result.current.continueSession.mutateAsync(quote);
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/continue", {
    confirmed: true,
    budget_usd: "1",
    estimate_usd: "0.04",
    candidate_hash: "hash",
  });
  await result.current.discard.mutateAsync();
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/discard", {
    confirmed: true,
  });
});

it("stores a person's sorting of one example and shows the answer at once", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], sample_limit: 20, training_failures: 0 });
  const sorted = { items: [], sample_limit: 21, training_failures: 0 };
  vi.mocked(apiClient.put).mockResolvedValue(sorted);
  const { result } = renderHook(() => useImprovementEvidence("a1", { sessionId: "s1" }), {
    wrapper,
  });
  await waitFor(() => expect(result.current.evidence?.sample_limit).toBe(20));
  await result.current.decide.mutateAsync({ runId: "r1", decision: "ignored" });
  expect(apiClient.put).toHaveBeenCalledWith("/agents/a1/improvements/s1/evidence/r1", {
    decision: "ignored",
  });
  await waitFor(() => expect(result.current.evidence?.sample_limit).toBe(21));
});
