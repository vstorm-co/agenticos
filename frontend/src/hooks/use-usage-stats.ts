"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import type { RatingsSummary, UsageScope, UsageStats } from "@/types/stats";

/** An inclusive ISO date window, as GET /stats/usage takes it. */
export interface UsagePeriod {
  from: string;
  to: string;
}

/**
 * Narrowing one card asks for beyond the window - one agent, one person.
 *
 * It rides the query key as well as the request, so a card pinned to an agent
 * and a card asking about everybody are two cached answers rather than one that
 * keeps overwriting the other. Empty means the organization's whole window,
 * which is what nearly every card asks and what they therefore share.
 */
export interface UsageFilter {
  agentId?: string;
  userId?: string;
}

/** The filter as the endpoint's own parameters; omitted when there is none. */
function filterParams(filter: UsageFilter | undefined): Record<string, string> {
  const params: Record<string, string> = {};
  if (filter?.agentId) params.agent_id = filter.agentId;
  if (filter?.userId) params.user_id = filter.userId;
  return params;
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
  options?: { scope?: UsageScope; enabled?: boolean; filter?: UsageFilter },
) {
  const scope = options?.scope ?? "org";
  const filter = options?.filter;
  const { data, isLoading, isPlaceholderData, error, refetch } = useQuery({
    queryKey: qk.stats.usage(scope, period.from, period.to, filter),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: { from: period.from, to: period.to, scope, ...filterParams(filter) },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  // `isPlaceholderData` is "this is the previous window's answer, still on
  // screen" - which the caller shows as stale rather than as loading. It is
  // false on the first load, when there is nothing to hold and a skeleton is
  // the honest state.
  return { usage: data ?? null, isLoading, isStale: isPlaceholderData, error, refetch };
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
    ...DASHBOARD_FRESHNESS,
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
  options?: { scope?: UsageScope; enabled?: boolean; limit?: number; filter?: UsageFilter },
) {
  const scope = options?.scope ?? "org";
  const limit = options?.limit ?? 6;
  // Only the agent half: this answer *is* the per-person split, so narrowing it
  // to one person would be a table of one row asking who used something.
  const filter: UsageFilter = { agentId: options?.filter?.agentId };
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.stats.usageByUser(scope, period.from, period.to, limit, filter),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: {
          from: period.from,
          to: period.to,
          scope,
          group_by: "user",
          limit: String(limit),
          ...filterParams(filter),
        },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { byUser: data?.by_user ?? [], isLoading, error, refetch };
}

/**
 * When the window's runs happened, by weekday and hour.
 *
 * Its own request rather than a block of the composed response, for the same
 * reason the version and person questions are: a hundred and sixty-eight cells
 * do not belong in every dashboard load, and only one card asks.
 */
export function useUsageByHour(
  period: UsagePeriod,
  options?: { scope?: UsageScope; enabled?: boolean; filter?: UsageFilter },
) {
  const scope = options?.scope ?? "org";
  const filter = options?.filter;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.stats.usageByHour(scope, period.from, period.to, filter),
    queryFn: () =>
      apiClient.get<UsageStats>("/stats/usage", {
        params: {
          from: period.from,
          to: period.to,
          scope,
          group_by: "hour",
          ...filterParams(filter),
        },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { byHour: data?.by_hour ?? [], isLoading, error, refetch };
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
    ...DASHBOARD_FRESHNESS,
  });
  return { ratings: data ?? null, isLoading, error, refetch };
}
