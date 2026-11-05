"use client";

import { useQuery } from "@tanstack/react-query";

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
 * Never stale: a change set is written once, when its task ends. Not retried
 * either - a 404 means the reader may not see it, and asking again will not
 * change that.
 */
export function useCodingChanges(changeId: string): UseCodingChangesResult {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.codingChanges.detail(changeId),
    queryFn: () => readCodingChanges(changeId),
    staleTime: Infinity,
    retry: false,
  });
  return { changes: data ?? null, isLoading, failed: isError };
}
