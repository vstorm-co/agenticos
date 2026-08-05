"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type { AgentRunList, ApprovalList, CostSummary, ToolApproval } from "@/types/runs";

/** Run history for the organization, or for one agent. */
export function useRuns(agentId?: string, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.list(agentId),
    queryFn: () =>
      apiClient.get<AgentRunList>("/runs", agentId ? { params: { agent_id: agentId } } : undefined),
    enabled: options?.enabled ?? true,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
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

  const { data, isLoading, error, refetch } = useQuery({
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

  return { approvals: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch, decide };
}

/** Month-to-date spend plus a per-agent breakdown. */
export function useSpend(days = 30) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.spend(days),
    queryFn: () => apiClient.get<CostSummary>("/spend", { params: { days: String(days) } }),
  });
  return { spend: data, isLoading, error, refetch };
}
