"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { RatingsSummary, UsageScope, UsageStats } from "@/types/stats";

/** An inclusive ISO date window, as GET /stats/usage takes it. */
export interface UsagePeriod {
  from: string;
  to: string;
}

/**
 * The composed usage answer for one window.
 *
 * Several widgets call this with the same arguments on purpose: React Query
 * dedupes them into one request, which is the composed response's whole point
 * - while every widget keeps its own error card, and any card's Retry
 * refetches the shared query for all of them.
 */
export function useUsageStats(
  period: UsagePeriod,
  options?: { scope?: UsageScope; enabled?: boolean },
) {
  const scope = options?.scope ?? "org";
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.stats.usage(scope, period.from, period.to),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: { from: period.from, to: period.to, scope },
      }),
    enabled: options?.enabled ?? true,
  });
  return { usage: data ?? null, isLoading, error, refetch };
}

/** Per-version rows for one agent - the version-compare card's question. */
export function useVersionUsage(
  agentId: string | null,
  period: UsagePeriod,
  options?: { enabled?: boolean },
) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.stats.usageByVersion(agentId ?? "none", period.from, period.to),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: {
          from: period.from,
          to: period.to,
          group_by: "version",
          agent_id: agentId ?? "",
        },
      }),
    // No agent picked yet (the composed answer has not arrived, or no agent
    // has two versions with runs) - there is nothing to ask about.
    enabled: (options?.enabled ?? true) && agentId !== null,
  });
  return { byVersion: data?.by_version ?? [], isLoading, error, refetch };
}

/** Answer quality for the window: the thumbs split and its per-day series. */
export function useRatingsSummary(
  period: UsagePeriod,
  options?: { scope?: UsageScope; enabled?: boolean },
) {
  const scope = options?.scope ?? "org";
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.ratings.summary(scope, period.from, period.to),
    queryFn: () =>
      apiClient.get<RatingsSummary>("/ratings/summary", {
        params: { from: period.from, to: period.to, scope },
      }),
    enabled: options?.enabled ?? true,
  });
  return { ratings: data ?? null, isLoading, error, refetch };
}
