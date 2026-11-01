"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { getWorkflowApprovalsSummary, getWorkflowsSummary } from "@/lib/workflows/workflows-api";

/** The real runs of every workflow the caller may see, on the inclusive days given. */
export function useWorkflowsSummary(from: string, to: string) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.workflows.summary(from, to),
    queryFn: () => getWorkflowsSummary(from, to),
  });
  return { summary: data ?? null, isLoading, error, refetch };
}

/** How people decided the approval steps of every workflow the caller may see, on the inclusive days given. */
export function useWorkflowApprovalsSummary(from: string, to: string) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.workflows.approvalsSummary(from, to),
    queryFn: () => getWorkflowApprovalsSummary(from, to),
  });
  return { summary: data ?? null, isLoading, error, refetch };
}
