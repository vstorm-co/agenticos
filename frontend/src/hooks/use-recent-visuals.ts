"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { listRecentVisuals } from "@/lib/visuals-api";

/** The caller's latest drawings in the active organization, newest first. */
export function useRecentVisuals(limit: number) {
  const query = useQuery({
    queryKey: qk.visuals.recent(limit),
    queryFn: () => listRecentVisuals(limit),
    // Activity, drawn in chat while this page is away: asked again each time the
    // card mounts rather than served from a cache minutes old.
    staleTime: 0,
    refetchOnMount: "always",
  });
  return {
    visuals: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
