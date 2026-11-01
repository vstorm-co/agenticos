"use client";
import { useQuery } from "@tanstack/react-query";
import { version } from "../../package.json";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { CurrentReleaseResponse } from "@/lib/releases";
export function useCurrentRelease(enabled: boolean) {
  return useQuery({
    queryKey: qk.releases.current(version),
    queryFn: () => apiClient.get<CurrentReleaseResponse>("/releases/current"),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
