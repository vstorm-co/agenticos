"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  AgentAuthoring,
  AuthoringEstimate,
  AuthoringRequest,
  AuthoringStart,
  AuthoringWaiting,
  HunkDecision,
  ProposalCheck,
} from "@/types/authoring";
import type { AgentSpec } from "@/types/agents";
import type { EvalRun, EvalRunEstimate } from "@/types/eval-runs";

/** How often a request the worker is still on is read again. */
export const AUTHORING_POLL_MS = 3_000;

function working(request: AuthoringRequest | null | undefined): boolean {
  return request?.status === "queued" || request?.status === "running";
}

/**
 * The assistant on one agent: the suggestions waiting for its draft and the
 * latest requests, read again while one is still being worked on, and every
 * action the strip offers.
 */
export function useAgentAuthoring(agentId: string, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.authoring.agent(agentId),
    queryFn: () => apiClient.get<AgentAuthoring>(`/agents/${agentId}/authoring`),
    enabled,
    refetchInterval: (current) => (working(current.state.data?.latest) ? AUTHORING_POLL_MS : false),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.authoring.all() }),
      queryClient.invalidateQueries({ queryKey: qk.agents.detail(agentId) }),
    ]);

  // No `onError` on these: a refusal - nothing to read, no budget, a stale
  // suggestion - is shown where the person acted, in the dialog or on the card.
  const estimate = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringEstimate>(`/agents/${agentId}/authoring/estimate`, body),
  });
  const start = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringRequest>(`/agents/${agentId}/authoring`, body),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: ({ hunkId, ...decision }: HunkDecision & { hunkId: string }) =>
      apiClient.post<{ authoring: AgentAuthoring; draft_spec: AgentSpec }>(
        `/agents/${agentId}/authoring/hunks/${hunkId}`,
        decision,
      ),
    onSuccess: (decided) => {
      queryClient.setQueryData(qk.authoring.agent(agentId), decided.authoring);
      return refresh();
    },
  });
  const dismissAll = useMutation({
    mutationFn: () => apiClient.post<AgentAuthoring>(`/agents/${agentId}/authoring/dismiss`),
    onSuccess: (read) => {
      queryClient.setQueryData(qk.authoring.agent(agentId), read);
      return refresh();
    },
  });
  const checkEstimate = useMutation({
    mutationFn: (body: ProposalCheck) =>
      apiClient.post<EvalRunEstimate>(`/agents/${agentId}/authoring/check/estimate`, body),
  });
  const check = useMutation({
    mutationFn: (body: ProposalCheck) =>
      apiClient.post<EvalRun>(`/agents/${agentId}/authoring/check`, body),
    onSuccess: () =>
      Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() })]),
  });

  return {
    authoring: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    estimate,
    start,
    decide,
    dismissAll,
    checkEstimate,
    check,
  };
}

/** The assistant on one skill: its latest requests, and starting another. */
export function useSkillAuthoring(skillId: string, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.authoring.skill(skillId),
    queryFn: () => apiClient.get<AuthoringRequest[]>(`/skills/${skillId}/authoring`),
    enabled,
    refetchInterval: (current) => (working(current.state.data?.[0]) ? AUTHORING_POLL_MS : false),
  });
  const estimate = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringEstimate>(`/skills/${skillId}/authoring/estimate`, body),
  });
  const start = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringRequest>(`/skills/${skillId}/authoring`, body),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.authoring.all() }),
        queryClient.invalidateQueries({ queryKey: qk.skillChanges.all() }),
      ]),
  });
  const checkEstimate = useMutation({
    mutationFn: (body: ProposalCheck) =>
      apiClient.post<EvalRunEstimate>(`/skills/${skillId}/authoring/check/estimate`, body),
  });
  const check = useMutation({
    mutationFn: (body: ProposalCheck) =>
      apiClient.post<EvalRun>(`/skills/${skillId}/authoring/check`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() }),
  });
  return {
    requests: query.data ?? [],
    latest: query.data?.[0] ?? null,
    estimate,
    start,
    checkEstimate,
    check,
  };
}

/** What the assistant proposed that the caller may decide, for the dashboard. */
export function useWaitingSuggestions({ enabled = true } = {}) {
  const query = useQuery({
    queryKey: qk.authoring.waiting(),
    queryFn: () => apiClient.get<AuthoringWaiting>("/authoring/waiting"),
    enabled,
  });
  return {
    waiting: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
