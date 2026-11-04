"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { LatestReleaseResponse } from "@/lib/releases";

export function useReleaseUpdate() {
  return useQuery({
    queryKey: qk.releases.latest(),
    queryFn: () => apiClient.get<LatestReleaseResponse>("/releases/latest"),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchInterval: 30 * 60_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
}
