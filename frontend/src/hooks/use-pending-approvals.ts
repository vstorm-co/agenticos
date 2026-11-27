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
 * The steps are read only for a caller holding `approvals:decide`, which that
 * list requires. The calls are read for everyone: without the permission the
 * server lists only the caller's own platform calls that always ask, which
 * nobody else may approve - `decidesAll` says which of the two the caller reads.
 * The server narrows each queue to what the console may decide - a step's
 * approval audience, and no call a live voice call is deciding - and counts it
 * across every page, so the first few rows come with the whole count.
 *
 * Until the caller's permissions are in, or after they failed to load, nothing
 * here is known: `isLoading` and `error` say so rather than a count of zero.
 */
export function usePendingApprovals() {
  const permissions = usePermissions();
  const loaded = permissions.isLoaded;
  const allowed = loaded && permissions.can(Perm.approvalsDecide);
  const tools = useQuery({
    queryKey: qk.runs.approvalsWaitingOnMe(),
    queryFn: () =>
      apiClient.get<ApprovalList>("/approvals", {
        params: { outside_live_calls: "true", limit: String(FIRST_ROWS) },
      }),
    staleTime: 30_000,
    gcTime: 30 * 60_000,
    refetchInterval: 30_000,
    enabled: loaded,
  });
  const steps = useQuery({
    queryKey: qk.workflows.approvalsWaitingOnMe(),
    queryFn: () => listDecidableWorkflowApprovals(FIRST_ROWS),
    staleTime: 30_000,
    gcTime: 30 * 60_000,
    refetchInterval: 30_000,
    enabled: allowed,
  });
  const reads = allowed ? [tools, steps] : [tools];
  return {
    decidesAll: allowed,
    tools: loaded ? (tools.data?.items ?? []) : [],
    steps: allowed ? (steps.data?.items ?? []) : [],
    count: loaded ? (tools.data?.total ?? 0) + (allowed ? (steps.data?.total ?? 0) : 0) : 0,
    isLoading: permissions.isLoading || (loaded && reads.some((read) => read.isLoading)),
    error: permissions.error ?? (loaded ? (reads.find((read) => read.error)?.error ?? null) : null),
    refetch: !loaded
      ? () => permissions.refetch()
      : () => Promise.all(reads.map((read) => read.refetch())),
  };
}
