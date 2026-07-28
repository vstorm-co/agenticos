"use client";

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { MyPermissions, Permission, PermissionScope, RoleCatalog } from "@/types/permissions";

/**
 * The caller's effective permissions in the active organization.
 *
 * `can()` decides what to *show*. It is never what decides what happens — every
 * endpoint re-checks server-side, so hiding a button is a courtesy to the user,
 * not a security boundary. While permissions are loading `can()` returns false,
 * which makes the UI reveal actions rather than briefly offer ones that would
 * be refused.
 *
 * `error` is returned because that same conservatism is a trap when the request
 * never succeeds: an organization the server refuses leaves `can()` answering
 * false forever, and the sidebar drops to four entries with nothing said. This
 * hook is deliberately not where that gets fixed — it is rendered by a dozen
 * components at once and would fire a dozen recoveries — but it is where the
 * refusal is visible. `useActiveOrganizationRecovery` reads it, once.
 */
export function usePermissions() {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);

  const { data, isLoading, error } = useQuery({
    queryKey: qk.organizations.permissions(activeOrgId ?? "current"),
    queryFn: () => apiClient.get<MyPermissions>("/me/permissions"),
    // A refused organization is refused again the same way; the retry only
    // delays the recovery. Everything else keeps the client's single retry,
    // because a dropped connection often does succeed the second time.
    retry: (failureCount, cause) =>
      !(cause instanceof ApiError && cause.status === 404) && failureCount < 1,
  });

  const can = useCallback(
    (permission: Permission) =>
      data?.permissions.some((entry) => entry.permission === permission) ?? false,
    [data],
  );

  const scopeOf = useCallback(
    (permission: Permission): PermissionScope =>
      data?.permissions.find((entry) => entry.permission === permission)?.scope ?? "none",
    [data],
  );

  const canAll = useCallback(
    (...permissions: Permission[]) => permissions.every((permission) => can(permission)),
    [can],
  );

  return {
    can,
    canAll,
    scopeOf,
    role: data?.role ?? "",
    isAppAdmin: data?.is_app_admin ?? false,
    isLoading,
    error,
  };
}

/**
 * The platform's full permission catalog and what each built-in role bundles.
 *
 * Readable by any member — it describes the rules, not the org's data — and is
 * what the Users & Roles matrix renders. Cached indefinitely: the catalog only
 * changes when the backend is redeployed.
 */
export function useRoleCatalog() {
  const { data, isLoading } = useQuery({
    queryKey: qk.organizations.roleCatalog(),
    queryFn: () => apiClient.get<RoleCatalog>("/roles/catalog"),
    staleTime: Infinity,
  });

  return { catalog: data, isLoading };
}
