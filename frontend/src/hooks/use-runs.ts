"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
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
 */
export function useRuns(agentId?: string, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.list(agentId),
    queryFn: () =>
      apiClient.get<AgentRunList>(
        "/runs",
        agentId ? { params: { agent_id: agentId, include_delegations: "true" } } : undefined,
      ),
    enabled: options?.enabled ?? true,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}

/**
 * One run, by id - where a link from somewhere else lands.
 *
 * Fetched on its own rather than found in the list, because the run being asked
 * about is usually a delegated one and the list deliberately does not contain
 * those. Disabled until there is an id, so the caller can render one component
 * for "a run was named" and "none was".
 */
export function useRun(runId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.detail(runId ?? "none"),
    queryFn: () => apiClient.get<AgentRun>(`/runs/${runId as string}`),
    enabled: runId !== null,
  });
  return { run: data, isLoading, error };
}

/** What one run delegated - the rows the top-level list leaves out. */
export function useDelegatedRuns(parentRunId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.runs.delegations(parentRunId ?? "none"),
    queryFn: () =>
      apiClient.get<AgentRunList>("/runs", {
        params: { parent_run_id: parentRunId as string },
      }),
    enabled: parentRunId !== null,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/**
 * The approval queue.
 *
 * Polled rather than pushed: a parked run is waiting on a person who may not
 * have the page open, and a thirty-second refresh is enough for a queue whose
 * items are minutes old.
 */
export function useApprovals() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.runs.approvals(),
    queryFn: () => apiClient.get<ApprovalList>("/approvals"),
    refetchInterval: 30_000,
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

  return { approvals: data?.items ?? [], total: data?.total ?? 0, isLoading, decide };
}

/** Month-to-date spend plus a per-agent breakdown. */
export function useSpend(days = 30) {
  const { data, isLoading } = useQuery({
    queryKey: qk.runs.spend(days),
    queryFn: () => apiClient.get<CostSummary>("/spend", { params: { days: String(days) } }),
  });
  return { spend: data, isLoading };
}
