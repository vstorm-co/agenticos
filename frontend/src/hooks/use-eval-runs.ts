"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  CaseOutcomeFilter,
  EvalCaseList,
  EvalComparison,
  EvalRun,
  EvalRunEstimate,
  EvalRunList,
  EvalRunRequest,
  EvalRunStatus,
} from "@/types/eval-runs";

/** How often a run still answering cases is read again. */
export const LIVE_POLL_MS = 3_000;

const LIVE: readonly EvalRunStatus[] = ["queued", "running"];

/** Whether a run is still answering cases, so its numbers can still move. */
export function isLive(status: EvalRunStatus): boolean {
  return LIVE.includes(status);
}

/**
 * One agent's eval runs, newest first, and starting one. `null` while the agent
 * is still to be chosen - a run started from a dataset picks it in the dialog.
 */
export function useEvalRuns(agentId: string | null, { skip = 0, limit = 20 } = {}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.evalRuns.forAgent(agentId ?? "", { skip, limit }),
    queryFn: () =>
      apiClient.get<EvalRunList>(`/agents/${agentId}/eval-runs?skip=${skip}&limit=${limit}`),
    enabled: agentId !== null,
    refetchInterval: (current) =>
      current.state.data?.items.some((run) => isLive(run.status)) ? LIVE_POLL_MS : false,
  });

  // No `onError` on either: a refusal - over budget, nothing to score - is
  // something the person fixes in the dialog still on screen.
  const estimate = useMutation({
    mutationFn: (request: EvalRunRequest) =>
      apiClient.post<EvalRunEstimate>(`/agents/${agentId}/eval-runs/estimate`, request),
  });
  const start = useMutation({
    mutationFn: (request: EvalRunRequest) =>
      apiClient.post<EvalRun>(`/agents/${agentId}/eval-runs`, request),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() }),
  });

  return {
    runs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    estimate,
    start,
  };
}

/** One run, read again while it is live, and stopping it. */
export function useEvalRun(runId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.evalRuns.detail(runId),
    queryFn: () => apiClient.get<EvalRun>(`/eval-runs/${runId}`),
    refetchInterval: (current) =>
      current.state.data && isLive(current.state.data.status) ? LIVE_POLL_MS : false,
  });
  const cancel = useMutation({
    mutationFn: () => apiClient.post<EvalRun>(`/eval-runs/${runId}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() }),
  });
  return {
    run: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    cancel,
  };
}

export interface CaseQuery {
  arm?: string | null;
  outcome?: CaseOutcomeFilter | null;
  tag?: string | null;
  skip?: number;
  limit?: number;
  /** Whether the run is still answering, so the table is read again while it is. */
  live?: boolean;
}

/** A page of a run's cases, each with every attempt every arm made at it. */
export function useEvalCases(
  runId: string,
  { arm = null, outcome = null, tag = null, skip = 0, limit = 50, live = false }: CaseQuery = {},
) {
  const query = useQuery({
    queryKey: qk.evalRuns.cases(runId, { arm, outcome, tag, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
      if (arm) params.set("arm_id", arm);
      if (outcome) params.set("outcome", outcome);
      if (tag) params.set("tag", tag);
      return apiClient.get<EvalCaseList>(`/eval-runs/${runId}/cases?${params}`);
    },
    placeholderData: (previous) => previous,
    refetchInterval: live ? LIVE_POLL_MS : false,
  });
  return {
    cases: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * A candidate arm against its baseline - the default one unless another run is
 * named. Read again while the run is live, since its verdict moves with every
 * case answered and nothing else marks it stale when the run finishes.
 */
export function useEvalComparison(
  runId: string,
  {
    arm = null,
    baseline = null,
    live = false,
  }: { arm?: string | null; baseline?: string | null; live?: boolean } = {},
) {
  const query = useQuery({
    queryKey: qk.evalRuns.comparison(runId, { arm, baseline }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (arm) params.set("arm_id", arm);
      if (baseline) params.set("baseline_run_id", baseline);
      const suffix = params.size ? `?${params}` : "";
      return apiClient.get<EvalComparison>(`/eval-runs/${runId}/comparison${suffix}`);
    },
    refetchInterval: live ? LIVE_POLL_MS : false,
  });
  return {
    comparison: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** The organization's latest runs the caller may read - the dashboard's card. */
export function useRecentEvalRuns(limit = 5, { enabled = true } = {}) {
  const query = useQuery({
    queryKey: qk.evalRuns.recent(limit),
    queryFn: () => apiClient.get<EvalRunList>(`/eval-runs/recent?limit=${limit}`),
    enabled,
  });
  return {
    runs: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
