"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { EvalRun } from "@/types/eval-runs";
import { qk } from "@/lib/query-keys";
import type {
  AttributionEstimate,
  ContinuationEstimate,
  KnowledgeCheckEstimate,
  KnowledgeCheckTarget,
  Improvement,
  ImprovementEstimate,
  ImprovementEvidence,
  SelectionEstimate,
  ImprovementTarget,
} from "@/types/improvement";

/**
 * A live session is refreshed by its `improvement` change event; this slower read
 * only covers a console whose live-updates socket is not connected.
 */
const IMPROVEMENT_FALLBACK_MS = 30_000;

export function useImprovements(agentId: string, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const base = `/agents/${agentId}/improvements`;
  const list = useQuery({
    queryKey: qk.improvements.agent(agentId),
    queryFn: () => apiClient.get<Improvement[]>(base),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.some((r) => ["queued", "running", "ready", "accepted"].includes(r.status))
        ? IMPROVEMENT_FALLBACK_MS
        : false,
  });
  const estimate = useMutation({
    mutationFn: (body: ImprovementTarget) =>
      apiClient.post<ImprovementEstimate>(`${base}/estimate`, body),
  });
  const start = useMutation({
    mutationFn: (body: ImprovementTarget & { budget_usd: string }) =>
      apiClient.post<Improvement>(base, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
  });
  return {
    sessions: list.data ?? [],
    isLoading: list.isLoading,
    error: list.error,
    estimate,
    start,
  };
}

export function useImprovement(agentId: string, runId: string) {
  const queryClient = useQueryClient();
  const base = `/agents/${agentId}/improvements/${runId}`;
  const query = useQuery({
    queryKey: qk.improvements.detail(agentId, runId),
    queryFn: () => apiClient.get<Improvement>(base),
    refetchInterval: (current) =>
      current.state.data &&
      ["queued", "running", "ready", "accepted"].includes(current.state.data.status)
        ? IMPROVEMENT_FALLBACK_MS
        : false,
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
      queryClient.invalidateQueries({ queryKey: qk.authoring.agent(agentId) }),
      queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() }),
    ]);
  };
  const estimateKnowledge = useMutation({
    mutationFn: (target: KnowledgeCheckTarget) =>
      apiClient.post<KnowledgeCheckEstimate>(`${base}/knowledge/estimate`, target),
  });
  const checkKnowledge = useMutation({
    mutationFn: (
      target: KnowledgeCheckTarget & { confirmed: true; draft_hash: string; estimate_usd: string },
    ) => apiClient.post<EvalRun>(`${base}/knowledge`, target),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: () => apiClient.post<Improvement>(`${base}/cancel`, {}),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: () => apiClient.post<Improvement>(`${base}/retry`, {}),
    onSuccess: refresh,
  });
  const selectRound = useMutation({
    mutationFn: (number: number) =>
      apiClient.post<Improvement>(`${base}/rounds/${number}/select`, {}),
    onSuccess: refresh,
  });
  const estimateAttribution = useMutation({
    mutationFn: (number: number) =>
      apiClient.post<AttributionEstimate>(`${base}/rounds/${number}/attribution/estimate`, {}),
  });
  const attribute = useMutation({
    mutationFn: ({ number, estimate }: { number: number; estimate: string }) =>
      apiClient.post<Improvement>(`${base}/rounds/${number}/attribution`, {
        confirmed: true,
        estimate_usd: estimate,
      }),
    onSuccess: refresh,
  });
  const estimateSelection = useMutation({
    mutationFn: ({ number, hunkIds }: { number: number; hunkIds: string[] }) =>
      apiClient.post<SelectionEstimate>(`${base}/rounds/${number}/selection/estimate`, {
        hunk_ids: hunkIds,
      }),
  });
  const checkSelection = useMutation({
    mutationFn: ({
      number,
      hunkIds,
      quote,
    }: {
      number: number;
      hunkIds: string[];
      quote: SelectionEstimate;
    }) =>
      apiClient.post<Improvement>(`${base}/rounds/${number}/selection`, {
        hunk_ids: hunkIds,
        confirmed: true,
        estimate_usd: quote.total_usd,
        candidate_hash: quote.candidate_hash,
      }),
    onSuccess: refresh,
  });
  const estimateContinuation = useMutation({
    mutationFn: (budget: string) =>
      apiClient.post<ContinuationEstimate>(`${base}/continue/estimate`, { budget_usd: budget }),
  });
  const continueSession = useMutation({
    mutationFn: (quote: ContinuationEstimate) =>
      apiClient.post<Improvement>(`${base}/continue`, {
        confirmed: true,
        budget_usd: quote.budget_usd,
        estimate_usd: quote.total_usd,
        candidate_hash: quote.candidate_hash,
      }),
    onSuccess: refresh,
  });
  const discard = useMutation({
    mutationFn: () => apiClient.post<Improvement>(`${base}/discard`, { confirmed: true }),
    onSuccess: refresh,
  });
  const finish = useMutation({
    mutationFn: (body: { confirmed: true; publish: boolean; automatic_check: boolean }) =>
      apiClient.post<{ session: Improvement; version_id: string | null; version: number | null }>(
        `${base}/finish`,
        body,
      ),
    onSuccess: refresh,
  });
  return {
    estimateContinuation,
    continueSession,
    discard,
    estimateKnowledge,
    checkKnowledge,
    estimateSelection,
    checkSelection,
    finish,
    session: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    cancel,
    retry,
    selectRound,
    estimateAttribution,
    attribute,
  };
}

export function useImprovementEvidence(
  agentId: string,
  {
    sessionId = null,
    datasetId = null,
    live = false,
  }: { sessionId?: string | null; datasetId?: string | null; live?: boolean } = {},
) {
  const query = useQuery({
    queryKey: qk.improvements.evidence(agentId, sessionId, datasetId),
    queryFn: () =>
      apiClient.get<ImprovementEvidence>(
        sessionId
          ? `/agents/${agentId}/improvements/${sessionId}/evidence`
          : `/agents/${agentId}/improvements/preview`,
        { params: !sessionId && datasetId ? { dataset_id: datasetId } : {} },
      ),
    refetchInterval: live ? IMPROVEMENT_FALLBACK_MS : false,
  });
  return {
    evidence: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
