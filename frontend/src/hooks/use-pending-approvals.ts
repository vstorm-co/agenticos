"use client";

import { useQuery } from "@tanstack/react-query";

import { usePermissions } from "@/hooks/use-permissions";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { listDecidableWorkflowApprovals } from "@/lib/workflows/approvals-api";
import type { ApprovalList } from "@/types/runs";
import { Perm } from "@/types/permissions";

/** How many rows of each queue are read; the inbox lists no more than that. */
const FIRST_ROWS = 5;

/**
 * What waits on the caller's decision: agents' parked tool calls and workflow
 * steps asking for approval, the two queues Activity → Approvals shows.
 *
 * Read only for a caller holding `approvals:decide`, which both lists require;
 * anyone else waits on nothing here and makes no request. The server narrows
 * each queue to what the console may decide - a step's approval audience, and
 * no call a live voice call is deciding - and counts it across every page, so
 * the first few rows come with the whole count.
 *
 * Until the caller's permissions are in, or after they failed to load, nothing
 * here is known: `isLoading` and `error` say so rather than a count of zero.
 */
export function usePendingApprovals() {
  const permissions = usePermissions();
  const allowed = permissions.can(Perm.approvalsDecide);
  const tools = useQuery({
    queryKey: qk.runs.approvalsWaitingOnMe(),
    queryFn: () =>
      apiClient.get<ApprovalList>("/approvals", {
        params: { outside_live_calls: "true", limit: String(FIRST_ROWS) },
      }),
    refetchInterval: 30_000,
    enabled: allowed,
  });
  const steps = useQuery({
    queryKey: qk.workflows.approvalsWaitingOnMe(),
    queryFn: () => listDecidableWorkflowApprovals(FIRST_ROWS),
    refetchInterval: 30_000,
    enabled: allowed,
  });
  const reads = [tools, steps];
  return {
    tools: allowed ? (tools.data?.items ?? []) : [],
    steps: allowed ? (steps.data?.items ?? []) : [],
    count: allowed ? (tools.data?.total ?? 0) + (steps.data?.total ?? 0) : 0,
    isLoading: permissions.isLoading || (allowed && reads.some((read) => read.isLoading)),
    error: permissions.error ?? (allowed ? (tools.error ?? steps.error) : null),
    refetch: !permissions.isLoaded
      ? () => permissions.refetch()
      : allowed
        ? () => Promise.all(reads.map((read) => read.refetch()))
        : () => Promise.resolve(),
  };
}
