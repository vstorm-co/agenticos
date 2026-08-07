"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type { AgentRun, AgentRunList, ApprovalList, CostSummary, ToolApproval } from "@/types/runs";

/**
 * Run history for the organization, or for one agent.
 *
 * The two are different questions and take opposite arithmetic, which is why
 * `agentId` changes more than a filter. Without one this is the organization's
 * history and delegated rows are excluded, so the count agrees with a bill that
 * charges a parent's run once. With one it is what *that agent* did, and its
 * delegated rows are the only record of that - an agent which only ever runs as
 * somebody's delegate would otherwise show an empty history beside a spend
 * figure of forty dollars.
 *
 * One run's delegations are asked for by parent, with `useDelegatedRuns`.
 *
 * `startedFrom` windows both the rows and `total`. It exists because a count with
 * no window reads *all time* while a spend figure beside it reads one calendar
 * month, so an organization three years old showed "8,412 runs" next to "$31.20"
 * and the obvious reading of the pair was wrong by three years (#198). Any figure
 * drawn next to money passes one.
 */
export function useRuns(agentId?: string, options?: { enabled?: boolean; startedFrom?: string }) {
  const startedFrom = options?.startedFrom;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.list(agentId, startedFrom),
    queryFn: () => {
      const params: Record<string, string> = {};
      if (agentId) {
        params.agent_id = agentId;
        params.include_delegations = "true";
      }
      if (startedFrom) params.started_from = startedFrom;
      return apiClient.get<AgentRunList>(
        "/runs",
        Object.keys(params).length > 0 ? { params } : undefined,
      );
    },
    enabled: options?.enabled ?? true,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}

/**
 * One run, by id - where a link from somewhere else lands.
 *
 * Fetched on its own rather than found in the list, because the run being asked
 * about is usually a delegated one and the list deliberately does not contain
 * those. `error` is returned because a run that is gone and a run the caller may
 * not read are the same absence, and only one of them is the reader's problem.
 */
export function useRun(runId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.detail(runId),
    queryFn: () => apiClient.get<AgentRun>(`/runs/${runId}`),
  });
  return { run: data, isLoading, error };
}

/** What one run delegated - the rows the top-level list leaves out. */
export function useDelegatedRuns(parentRunId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.runs.delegations(parentRunId),
    queryFn: () => apiClient.get<AgentRunList>("/runs", { params: { parent_run_id: parentRunId } }),
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/**
 * The approval queue.
 *
 * Polled rather than pushed: a parked run is waiting on a person who may not
 * have the page open, and a thirty-second refresh is enough for a queue whose
 * items are minutes old.
 *
 * `enabled` is how a caller without `approvals:decide` opts out, and it is not a
 * cosmetic choice: reading the queue takes the same permission as deciding one,
 * so a refused caller would answer 403 every thirty seconds for as long as the
 * page stayed open. It matters more that an empty list is then unambiguous -
 * with the query disabled there is no `[]` from a refusal for the queue to draw
 * as "nothing waiting".
 */
export function useApprovals(options?: { enabled?: boolean }) {
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.approvals(),
    queryFn: () => apiClient.get<ApprovalList>("/approvals"),
    refetchInterval: 30_000,
    enabled: options?.enabled ?? true,
  });

  const decide = useMutation({
    mutationFn: ({ id, approved, note }: { id: string; approved: boolean; note?: string }) =>
      apiClient.post<ToolApproval>(`/approvals/${id}`, { approved, note }),
    onSuccess: async (approval) => {
      await queryClient.invalidateQueries({ queryKey: qk.runs.all() });
      toast.success(approval.status === "approved" ? "Approved" : "Rejected");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    approvals: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    decide,
    refetch,
  };
}

/**
 * Month-to-date spend and its breakdowns.
 *
 * Carries the dashboard's freshness even though the runs page and the
 * organization's spending-limit control read it too: a spend figure is the
 * last number anybody wants served from a five-minute cache, and refetching
 * it when a tab regains focus is right on all three surfaces.
 *
 * `error` is returned because the tab reading it must be able to tell a failed
 * request from a month with no spend in it. Drawn from `data` alone the two are
 * the same "nothing spent yet", and on a page about money the wrong one of those
 * is the reassuring one.
 */
export function useSpend(days = 30) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.spend(days),
    queryFn: () => apiClient.get<CostSummary>("/spend", { params: { days: String(days) } }),
    ...DASHBOARD_FRESHNESS,
  });
  return { spend: data, isLoading, error, refetch };
}
