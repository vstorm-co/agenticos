"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { getAppBuildId, type AppVersion } from "@/lib/app-build";
import { qk } from "@/lib/query-keys";

/** Offer a reload when the deployed frontend differs from this open tab. */
export function useAppUpdate(): boolean {
  const buildId = getAppBuildId();
  const { data } = useQuery({
    queryKey: qk.appVersion(buildId),
    queryFn: async ({ signal }) => {
      const deployed = await apiClient.get<AppVersion | null>("/app-version", {
        cache: "no-store",
        signal,
      });
      return (
        typeof deployed?.buildId === "string" &&
        deployed.buildId.length > 0 &&
        deployed.buildId !== buildId
      );
    },
    // Keep an offered update through navigation and stop all further checks.
    enabled: (query) => Boolean(buildId) && query.state.data !== true,
    gcTime: Infinity,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    retry: false,
  });
  return data === true;
}
