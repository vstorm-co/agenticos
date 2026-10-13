"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import type { AdminOrganization } from "@/types/admin";

/** What the admin's organization list can be narrowed and ordered by. */
export const ADMIN_ORG_SORT_KEYS = ["name", "slug", "members", "agents", "created_at"] as const;

export type AdminOrgSort = (typeof ADMIN_ORG_SORT_KEYS)[number];
export type AdminOrgKind = "all" | "personal" | "team";

export interface AdminOrganizationQuery {
  skip?: number;
  limit?: number;
  search?: string;
  sortBy?: AdminOrgSort;
  sortDir?: "asc" | "desc";
  kind?: AdminOrgKind;
}

/**
 * Every tenant on the deployment - the admin list, and the top-organizations card.
 *
 * One hook and one query key for both, and the key carries the request. They
 * used to share a bare `["admin", "organizations"]` while asking for different
 * things: the card asks for five and the page for fifty of whatever it is
 * narrowed to, so whichever mounted first filled the cache and the other
 * rendered its answer.
 *
 * Narrowing, ordering and paging are the server's - `GET /admin/organizations`
 * applies all three in SQL before `OFFSET`/`LIMIT` (#921). Sorting one page
 * after it arrives would claim a whole-collection order that fifty rows cannot
 * deliver, which is why this list had no sort at all while the route answered
 * none.
 */
export function useAdminOrganizations(
  query: AdminOrganizationQuery = {},
  options?: { enabled?: boolean },
) {
  const params: Record<string, string> = { limit: String(query.limit ?? 50) };
  if (query.skip) params.skip = String(query.skip);
  if (query.search) params.search = query.search;
  if (query.sortBy) params.sort_by = query.sortBy;
  if (query.sortDir) params.sort_dir = query.sortDir;
  if (query.kind && query.kind !== "all") params.kind = query.kind;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.organizations(params),
    queryFn: () =>
      apiClient.get<{ items: AdminOrganization[]; total: number }>("/admin/organizations", {
        params,
      }),
    enabled: options?.enabled ?? true,
    // Which holds the last answer while the next is in flight, so paging and
    // sorting do not blank the table between them (#944's shape).
    ...DASHBOARD_FRESHNESS,
  });
  return {
    organizations: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
  };
}
