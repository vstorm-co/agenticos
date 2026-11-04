"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { listWorkflowLogs } from "@/lib/workflows/logs-api";
import type { LogQuery } from "@/lib/workflows/types";

/** A filtered page of a workflow's log. `error` is set when the request failed: not an empty log. */
export function useWorkflowLogs(query: LogQuery) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.workflows.logs(query),
    queryFn: () => listWorkflowLogs(query),
    placeholderData: (previous) => previous,
  });
  return { entries: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}
