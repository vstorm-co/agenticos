"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  EvalSuite,
  EvalSuiteEstimate,
  EvalSuiteEstimateRequest,
  EvalSuiteInput,
  EvalSuiteList,
  EvalSuiteResult,
  EvalSuiteResultList,
} from "@/types/eval-suites";

/**
 * One agent's eval suites, and the writes that change them.
 *
 * Mutations invalidate rather than patch: the server derives what a row shows -
 * the next fire in the owner's zone, the owner, the last result - and a client
 * guessing them would show a schedule nobody set. A run started here also
 * invalidates the eval runs, which list the run it started. A settled result
 * arrives on its own over `/ws/events`.
 */
export function useEvalSuites(agentId: string) {
  const queryClient = useQueryClient();
  const t = useTranslations("evals.suites");
  const tErrors = useTranslations("errors");
  const base = `/agents/${agentId}/eval-suites`;

  const query = useQuery({
    queryKey: qk.evalSuites.forAgent(agentId),
    queryFn: () => apiClient.get<EvalSuiteList>(base),
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.evalSuites.all() });
    await queryClient.invalidateQueries({ queryKey: qk.evalRuns.all() });
  }, [queryClient]);
  const failed = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  // No `onError` on create or update: a refusal names a field, and the form
  // still on screen is where it is shown.
  const create = useMutation({
    mutationFn: (input: EvalSuiteInput) => apiClient.post<EvalSuite>(base, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
  });
  const update = useMutation({
    mutationFn: ({ suiteId, input }: { suiteId: string; input: EvalSuiteInput }) =>
      apiClient.patch<EvalSuite>(`${base}/${suiteId}`, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("saved"));
    },
  });
  const setActive = useMutation({
    // Only `is_active`, so a pause cannot overwrite what somebody changed meanwhile.
    mutationFn: ({ suiteId, isActive }: { suiteId: string; isActive: boolean }) =>
      apiClient.patch<EvalSuite>(`${base}/${suiteId}`, { is_active: isActive }),
    onSuccess: async (suite) => {
      await invalidate();
      toast.success(suite.is_active ? t("resumedToast") : t("pausedToast"));
    },
    onError: failed,
  });
  const runNow = useMutation({
    mutationFn: (suiteId: string) => apiClient.post<EvalSuiteResult>(`${base}/${suiteId}/run`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("runningToast"));
    },
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: (suiteId: string) => apiClient.delete<void>(`${base}/${suiteId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("removed"));
    },
    onError: failed,
  });
  const movePin = useMutation({
    mutationFn: (suiteId: string) => apiClient.post<EvalSuite>(`${base}/${suiteId}/pin`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("pinMoved"));
    },
    onError: failed,
  });
  const estimate = useMutation({
    mutationFn: (request: EvalSuiteEstimateRequest) =>
      apiClient.post<EvalSuiteEstimate>(`${base}/estimate`, request),
  });

  return {
    suites: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    create,
    update,
    setActive,
    runNow,
    remove,
    movePin,
    estimate,
  };
}

/** One agent's eval suites, read only - for a picker that runs something against one. */
export function useAgentEvalSuites(agentId: string, { enabled = true } = {}) {
  const query = useQuery({
    queryKey: qk.evalSuites.forAgent(agentId),
    queryFn: () => apiClient.get<EvalSuiteList>(`/agents/${agentId}/eval-suites`),
    enabled,
  });
  return { suites: query.data?.items ?? [] };
}

/** One suite's results, newest first, a page at a time. */
export function useEvalSuiteResults(
  agentId: string,
  suiteId: string,
  {
    skip = 0,
    limit = 20,
    enabled = true,
  }: { skip?: number; limit?: number; enabled?: boolean } = {},
) {
  const query = useQuery({
    queryKey: qk.evalSuites.results(agentId, suiteId, { skip, limit }),
    queryFn: () =>
      apiClient.get<EvalSuiteResultList>(
        `/agents/${agentId}/eval-suites/${suiteId}/results?skip=${skip}&limit=${limit}`,
      ),
    enabled,
  });
  return {
    results: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
  };
}

/** Every suite on an agent the reader may see - the dashboard's view. */
export function useVisibleEvalSuites({ enabled = true }: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: qk.evalSuites.visible(),
    queryFn: () => apiClient.get<EvalSuiteList>("/eval-suites"),
    enabled,
  });
  return {
    suites: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
