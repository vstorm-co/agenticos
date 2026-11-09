"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-error";
import { readCodingChanges, type CodingTaskChanges } from "@/lib/coding-changes-api";
import { qk } from "@/lib/query-keys";

interface UseCodingChangesResult {
  changes: CodingTaskChanges | null;
  isLoading: boolean;
  failed: boolean;
}

/**
 * What one coding task changed, for the panel under it.
 *
 * Never stale: a change set is written once, when its task ends. A refusal is
 * not retried - a 404 means the reader may not see it, and asking again will
 * not change that - but a 5xx or a dropped connection keeps the client's single
 * retry, or the panel would stay empty after the server recovers.
 */
export function useCodingChanges(changeId: string): UseCodingChangesResult {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.codingChanges.detail(changeId),
    queryFn: () => readCodingChanges(changeId),
    staleTime: Infinity,
    retry: (failureCount, cause) =>
      !(cause instanceof ApiError && cause.status < 500) && failureCount < 1,
  });
  return { changes: data ?? null, isLoading, failed: isError };
}
