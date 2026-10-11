"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { getWorkflowStats } from "@/lib/workflows/workflows-api";

/** What a workflow's real runs did over the last `days` days. */
export function useWorkflowStats(workflowId: string, days: number) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.stats(workflowId, days),
    queryFn: () => getWorkflowStats(workflowId, days),
  });
  return { stats: data ?? null, isLoading, error };
}
