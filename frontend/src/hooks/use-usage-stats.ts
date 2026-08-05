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
 * Daily aggregates refresh when the tab comes back, against the app-wide
 * default of not refetching on focus.
 *
 * That default exists so navigating around does not re-ask every list, and it
 * is right for a page somebody is reading. A dashboard is a page somebody
 * leaves open: coming back to yesterday's numbers after lunch and acting on
 * them is the failure the app-wide setting has no way to see. The queue is a
 * separate matter and already polls - see `useApprovals`.
 */
const AGGREGATE_FRESHNESS = { refetchOnWindowFocus: true } as const;

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
    ...AGGREGATE_FRESHNESS,
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
    ...AGGREGATE_FRESHNESS,
  });
  return { byVersion: data?.by_version ?? [], isLoading, error, refetch };
}

/**
 * Per-person rows for the window - who is using it, busiest first.
 *
 * Its own query rather than a block of the composed response: it is the one
 * answer that names people, so it is asked for explicitly by the one card
 * that renders names. The count it sits under comes from the composed
 * response the same card already holds.
 */
export function usePeopleUsage(
  period: UsagePeriod,
  options?: { scope?: UsageScope; enabled?: boolean; limit?: number },
) {
  const scope = options?.scope ?? "org";
  const limit = options?.limit ?? 6;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.stats.usageByUser(scope, period.from, period.to, limit),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: {
          from: period.from,
          to: period.to,
          scope,
          group_by: "user",
          limit: String(limit),
        },
      }),
    enabled: options?.enabled ?? true,
    ...AGGREGATE_FRESHNESS,
  });
  return { byUser: data?.by_user ?? [], isLoading, error, refetch };
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
    ...AGGREGATE_FRESHNESS,
  });
  return { ratings: data ?? null, isLoading, error, refetch };
}
