"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

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
  ProposedSkill,
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
  const createSkill = useMutation({
    mutationFn: ({
      requestId,
      index,
      ...skill
    }: ProposedSkill & { requestId: string; index: number }) =>
      apiClient.post<{ authoring: AgentAuthoring; draft_spec: AgentSpec; skill_id: string }>(
        `/agents/${agentId}/authoring/requests/${requestId}/ideas/${index}/skill`,
        skill,
      ),
    onSuccess: (created) => {
      queryClient.setQueryData(qk.authoring.agent(agentId), created.authoring);
      return Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: qk.skills.all() })]);
    },
  });
  const decideIdea = useMutation({
    mutationFn: ({
      requestId,
      index,
      action,
    }: {
      requestId: string;
      index: number;
      action: "dismiss" | "undo";
    }) =>
      apiClient.post<AgentAuthoring>(
        `/agents/${agentId}/authoring/requests/${requestId}/ideas/${index}/decision`,
        { action },
      ),
    onSuccess: (read) => {
      queryClient.setQueryData(qk.authoring.agent(agentId), read);
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
    refetch: query.refetch,
    authoring: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    estimate,
    start,
    decide,
    createSkill,
    decideIdea,
    dismissAll,
    checkEstimate,
    check,
  };
}

/**
 * The assistant on one organization resource whose change waits whole - a skill
 * or a context file: its latest requests, starting another, and checking a change.
 *
 * The change it proposes is written when the request finishes, not when it is
 * queued, so the waiting changes are read again once the one being worked on ends.
 */
function useResourceAuthoring(
  base: string,
  queryKey: readonly unknown[],
  changes: readonly unknown[],
  { enabled = true } = {},
) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey,
    queryFn: () => apiClient.get<AuthoringRequest[]>(`${base}/authoring`),
    enabled,
    refetchInterval: (current) => (working(current.state.data?.[0]) ? AUTHORING_POLL_MS : false),
  });
  const latest = query.data?.[0];
  const workingOn = latest !== undefined && working(latest) ? latest.id : null;
  const watched = useRef<string | null>(null);
  useEffect(() => {
    if (watched.current !== null && watched.current !== workingOn) {
      void queryClient.invalidateQueries({ queryKey: changes });
    }
    watched.current = workingOn;
  }, [workingOn, queryClient, changes]);
  const estimate = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringEstimate>(`${base}/authoring/estimate`, body),
  });
  const start = useMutation({
    mutationFn: (body: AuthoringStart) =>
      apiClient.post<AuthoringRequest>(`${base}/authoring`, body),
    onSuccess: (request) => {
      queryClient.setQueryData<AuthoringRequest[]>(queryKey, (before = []) => [request, ...before]);
      return queryClient.invalidateQueries({ queryKey: qk.authoring.all() });
    },
  });
  const checkEstimate = useMutation({
    mutationFn: (body: ProposalCheck) =>
      apiClient.post<EvalRunEstimate>(`${base}/authoring/check/estimate`, body),
  });
  const check = useMutation({
    mutationFn: (body: ProposalCheck) => apiClient.post<EvalRun>(`${base}/authoring/check`, body),
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

/** The assistant on one skill. */
export function useSkillAuthoring(skillId: string, options: { enabled?: boolean } = {}) {
  return useResourceAuthoring(
    `/skills/${skillId}`,
    qk.authoring.skill(skillId),
    qk.skillChanges.all(),
    options,
  );
}

/** The assistant on one context file. */
export function useContextAuthoring(contextId: string, options: { enabled?: boolean } = {}) {
  return useResourceAuthoring(
    `/context/${contextId}`,
    qk.authoring.context(contextId),
    qk.contextChanges.all(),
    options,
  );
}

/**
 * Keeps reading every context file request this page has seen queued or running,
 * after whatever started it is gone.
 *
 * Improve is started from a file's editor, and the editor can close while the
 * assistant works; the change it then proposes still has to appear on the page.
 */
export function useContextAuthoringWatch() {
  const queryClient = useQueryClient();
  const [ids, setIds] = useState<string[]>([]);
  const watched = useRef<string[]>([]);
  useEffect(() => {
    const cache = queryClient.getQueryCache();
    const read = () => {
      const now = cache
        .findAll({ queryKey: qk.authoring.contexts() })
        .filter((query) => working((query.state.data as AuthoringRequest[] | undefined)?.[0]))
        .map((query) => String(query.queryKey[2]));
      const before = watched.current;
      if (now.length === before.length && now.every((id) => before.includes(id))) return;
      if (before.some((id) => !now.includes(id))) {
        void queryClient.invalidateQueries({ queryKey: qk.contextChanges.all() });
      }
      watched.current = now;
      setIds(now);
    };
    read();
    return cache.subscribe(read);
  }, [queryClient]);
  useQueries({
    queries: ids.map((id) => ({
      queryKey: qk.authoring.context(id),
      queryFn: () => apiClient.get<AuthoringRequest[]>(`/context/${id}/authoring`),
      refetchInterval: AUTHORING_POLL_MS,
    })),
  });
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
