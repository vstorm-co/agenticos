"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { OrganizationMember, OrganizationMemberList, OrgRole } from "@/types";

/** The largest page the route serves - `limit` is capped at 100. */
const PAGE = 100;

/**
 * Every member, not the first page of them.
 *
 * `GET /orgs/{id}/members` defaults to fifty and caps at a hundred, and this hook
 * asked for neither - so every caller was handed the first fifty and told the
 * total. On the members table that is a table missing rows; on the conversation
 * share dialog, whose picker is the only way to name somebody, it is a colleague
 * who cannot be shared with at all (#931).
 *
 * Paged rather than asked for in one request because the ceiling is the server's.
 * A **short page** is what ends it, rather than the count: `total` is the server's
 * claim about how many there are, and a loop that trusts it asks forever if it is
 * ever wrong. Fewer than a full page can only be the last one.
 */
async function everyMember(orgId: string): Promise<OrganizationMemberList> {
  const items: OrganizationMember[] = [];
  let total = 0;
  for (let skip = 0; ; skip += PAGE) {
    const page = await apiClient.get<OrganizationMemberList>(
      `/orgs/${orgId}/members?skip=${skip}&limit=${PAGE}`,
    );
    total = page.total;
    items.push(...page.items);
    if (page.items.length < PAGE) return { items, total };
  }
}

export function useMembers(orgId: string) {
  const queryClient = useQueryClient();
  // A toast is as user-facing as anything on screen, and the catalog already
  // held every one of these four - the guard walked `*.tsx` alone then, so no hook in
  // this directory had ever been read by it (#425). It reads them now.
  const t = useTranslations("members");

  // React Query owns the list: cached per-org, deduped, no refetch storms.
  // We cache the full list response so `total` survives alongside `members`,
  // and mutations patch the cache directly to keep the UI instant.
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.organizations.members(orgId),
    queryFn: () => everyMember(orgId),
    enabled: !!orgId,
  });

  const members = data?.items ?? [];
  const total = data?.total ?? 0;

  const writeCache = useCallback(
    (updater: (prev: OrganizationMemberList) => OrganizationMemberList) =>
      queryClient.setQueryData<OrganizationMemberList>(
        qk.organizations.members(orgId),
        (prev = { items: [], total: 0 }) => updater(prev),
      ),
    [queryClient, orgId],
  );

  // Kept for API compatibility: the list auto-fetches on mount; this forces a
  // background refresh.
  const fetchMembers = useCallback(() => {
    if (!orgId) return;
    queryClient.invalidateQueries({ queryKey: qk.organizations.members(orgId) });
  }, [queryClient, orgId]);

  const changeRole = useCallback(
    async (userId: string, role: OrgRole) => {
      try {
        const updated = await apiClient.patch<OrganizationMember>(
          `/orgs/${orgId}/members/${userId}`,
          { role },
        );
        writeCache((prev) => ({
          ...prev,
          items: prev.items.map((m) => (m.user_id === userId ? updated : m)),
        }));
        toast.success(t("roleUpdated"));
      } catch {
        toast.error(t("failedRole"));
      }
    },
    [orgId, writeCache, t],
  );

  const removeMember = useCallback(
    async (userId: string) => {
      try {
        await apiClient.delete(`/orgs/${orgId}/members/${userId}`);
        writeCache((prev) => ({
          items: prev.items.filter((m) => m.user_id !== userId),
          total: prev.total - 1,
        }));
        toast.success(t("memberRemoved"));
      } catch {
        toast.error(t("failedRemove"));
      }
    },
    [orgId, writeCache, t],
  );

  return { members, total, isLoading, error, refetch, fetchMembers, changeRole, removeMember };
}
