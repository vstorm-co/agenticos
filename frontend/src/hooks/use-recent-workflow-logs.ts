"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { getRecentWorkflowLogs } from "@/lib/workflows/recent-logs-api";

/** The newest real-run lines across every workflow the caller may view. `error` is set when the request failed: not a quiet log. */
export function useRecentWorkflowLogs(limit: number) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.workflows.recentLogs(limit),
    queryFn: () => getRecentWorkflowLogs(limit),
  });
  return { logs: data ?? null, isLoading, error, refetch };
}
