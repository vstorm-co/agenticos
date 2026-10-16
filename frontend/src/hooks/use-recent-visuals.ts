"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { listRecentVisuals } from "@/lib/visuals-api";

/** The caller's latest drawings in the active organization, newest first. */
export function useRecentVisuals(limit: number) {
  const query = useQuery({
    queryKey: qk.visuals.recent(limit),
    queryFn: () => listRecentVisuals(limit),
  });
  return {
    visuals: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
