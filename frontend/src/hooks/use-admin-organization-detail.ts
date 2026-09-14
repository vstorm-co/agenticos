"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { AdminOrganizationDetail } from "@/types/admin";

/**
 * One tenant in full for the deployment admin, from `GET /admin/organizations/{id}`.
 *
 * The destination the admin user-drawer's organization row links to (#1245): a
 * tenant an admin can open without belonging to it - the common case, since the
 * admin is a member of no tenant's personal organization. Metadata only (members
 * and roles, size, owner, budget), and the cross-tenant read is audited server
 * side. `enabled` is off until an id is in hand, so a closed drawer fetches
 * nothing.
 */
export function useAdminOrganizationDetail(orgId: string, options?: { enabled?: boolean }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.admin.organizationDetail(orgId),
    queryFn: () => apiClient.get<AdminOrganizationDetail>(`/admin/organizations/${orgId}`),
    enabled: options?.enabled ?? true,
    // Not the dashboard's refetch-on-focus: every successful read writes an
    // `admin.organization.read` audit entry, so refetching each time the window
    // regains focus would fill the trail with reads nobody made (#1245 review).
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  return { organization: data, isLoading, error, refetch };
}
