"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  AttributionEstimate,
  Improvement,
  ImprovementEstimate,
  ImprovementTarget,
} from "@/types/improvement";

export function useImprovements(agentId: string, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const base = `/agents/${agentId}/improvements`;
  const list = useQuery({
    queryKey: qk.improvements.agent(agentId),
    queryFn: () => apiClient.get<Improvement[]>(base),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.some((r) => ["queued", "running", "ready", "accepted"].includes(r.status))
        ? 3000
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
        ? 3000
        : false,
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
      queryClient.invalidateQueries({ queryKey: qk.authoring.agent(agentId) }),
      queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() }),
    ]);
  };
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
  const finish = useMutation({
    mutationFn: (body: { confirmed: true; publish: boolean; automatic_check: boolean }) =>
      apiClient.post<{ session: Improvement; version_id: string | null; version: number | null }>(
        `${base}/finish`,
        body,
      ),
    onSuccess: refresh,
  });
  return {
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
