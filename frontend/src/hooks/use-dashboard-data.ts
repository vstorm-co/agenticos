"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import { listSyncSources } from "@/lib/rag-api";
import { useOrgStore } from "@/stores";
import type { AdminOrganization, AdminStats, SystemHealth } from "@/types/admin";
import type { Conversation, RatingSummary } from "@/types/conversation";
import type { AgentRunList } from "@/types/runs";

/** Failed or out-of-budget runs, newest first - the recent-failures card. */
export function useRecentFailures(limit = 5, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.failures(limit),
    queryFn: () =>
      apiClient.get<AgentRunList>("/runs", {
        params: { status: "failed,budget_exceeded", limit: String(limit) },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { failures: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}

/** The organization's sync sources and their freshness - the knowledge-sync card. */
export function useSyncSources(options?: { enabled?: boolean }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.rag.syncSources(activeOrgId ?? "current"),
    queryFn: () => listSyncSources(),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { sources: data?.items ?? [], isLoading, error, refetch };
}

/** The newest few conversations - "continue where you left off". */
export function useRecentConversations(limit = 4, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.conversations.recent(limit),
    queryFn: () =>
      apiClient.get<{ items: Conversation[] }>("/conversations", {
        params: { limit: String(limit) },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { conversations: data?.items ?? [], isLoading, error, refetch };
}

export interface SharedWithMeCounts {
  agents: number;
  collections: number;
  skills: number;
}

/**
 * How much was deliberately shared with the caller, per resource type.
 *
 * One query for the card, so it has one loading state and one Retry. The
 * counts ride each listing's `total` under `shared_with_me=true` with
 * `limit=1` - except kb, whose listing is unpaged and answers with the rows
 * themselves.
 */
export function useSharedWithMeCounts(options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.dashboard.sharedWithMe(),
    queryFn: async (): Promise<SharedWithMeCounts> => {
      const [agents, collections, skills] = await Promise.all([
        apiClient.get<{ total: number }>("/agents", {
          params: { shared_with_me: "true", limit: "1" },
        }),
        apiClient.get<{ items: unknown[] }>("/kb", { params: { shared_with_me: "true" } }),
        apiClient.get<{ total: number }>("/skills", {
          params: { shared_with_me: "true", limit: "1" },
        }),
      ]);
      return {
        agents: agents.total,
        collections: collections.items.length,
        skills: skills.total,
      };
    },
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { counts: data ?? null, isLoading, error, refetch };
}

/** Deployment-wide counts - the app admin's "platform at a glance" card. */
export function useAdminStats(options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.stats(),
    queryFn: () => apiClient.get<AdminStats>("/admin/stats"),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { stats: data ?? null, isLoading, error, refetch };
}

/** Service probes - the app admin's health card. */
export function useSystemHealth(options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.system(),
    queryFn: () => apiClient.get<SystemHealth>("/admin/system"),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { health: data ?? null, isLoading, error, refetch };
}

/** The largest organizations - the app admin's top-organizations card. */
export function useAdminOrganizations(limit = 5, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.organizations(),
    queryFn: () =>
      apiClient.get<{ items: AdminOrganization[] }>("/admin/organizations", {
        params: { limit: String(limit) },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { organizations: data?.items ?? [], isLoading, error, refetch };
}

/** Deployment-wide answer quality - the app admin's ratings card. */
export function useAdminRatingsSummary(options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.ratings("summary"),
    queryFn: () =>
      apiClient.get<RatingSummary>("/admin/ratings/summary", { params: { days: "30" } }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { summary: data ?? null, isLoading, error, refetch };
}
