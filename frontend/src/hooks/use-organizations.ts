"use client";

import { useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { Organization, OrganizationList, CreateOrganizationInput } from "@/types";

/**
 * Every organization the caller belongs to.
 *
 * Split out because it is the one request that survives a broken selection:
 * `/orgs` is keyed on the caller, not on the `X-Organization-Id` header, so it
 * still answers when the active organization is one the server refuses. That
 * makes it the only sound basis for recovering from one - see
 * `use-active-organization.ts`.
 *
 * React Query owns the list: cached across navigations, deduped, no refetch
 * storms. Mutations patch the cache directly so the UI stays instant.
 */
export function useOrganizationList() {
  return useQuery({
    queryKey: qk.organizations.list(),
    queryFn: async () => (await apiClient.get<OrganizationList>("/orgs")).items,
  });
}

/**
 * The organization every request is actually made as.
 *
 * Not the same thing as the selection. `activeOrgId` is null until the list
 * loads and the default is picked, and a request sent meanwhile carries no
 * `X-Organization-Id` - which the backend reads as the caller's personal
 * organization, not as no organization at all. Anything comparing "has the
 * tenant changed?" has to compare this, or it reads a page finishing its first
 * render as somebody switching organizations.
 *
 * Still null while nothing can answer the question: no selection, and no list
 * to resolve the personal organization from. A caller deciding whether to throw
 * work away should treat that as "cannot tell yet" and do nothing.
 */
export function useTenantId(): string | null {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  return activeOrgId ?? orgs?.find((org) => org.is_personal)?.id ?? null;
}

/**
 * "Is the tenant I started in still the current one?", for code after an await.
 *
 * Every hook that writes state or the query cache after a request needs this,
 * and each one was reading `activeOrgId` straight from the store - which is
 * null on a freshly loaded page and so reported a change that had not happened.
 * The ref is what makes the current value readable outside render; it is
 * written from an effect, because the compiler rules forbid writing a ref
 * during one.
 */
export function useTenantGuard(): (startedIn: string | null) => boolean {
  const tenant = useTenantId();
  const current = useRef(tenant);
  useEffect(() => {
    current.current = tenant;
  });
  return useCallback((startedIn: string | null) => current.current === startedIn, []);
}

/**
 * The organization to select out of `orgs`: the caller's personal one, or
 * failing that whichever comes first. `null` when there is nothing to pick,
 * which leaves the header off and lets the server fall back for us.
 *
 * `refusedIds` are skipped. Selecting one back would undo a recovery that has
 * just moved off it, and the two would trade the selection indefinitely.
 */
export function preferredOrg(
  orgs: readonly Organization[],
  refusedIds: readonly string[] = [],
): Organization | null {
  const usable = orgs.filter((o) => !refusedIds.includes(o.id));
  return usable.find((o) => o.is_personal) ?? usable[0] ?? null;
}

export function useOrganizations() {
  const queryClient = useQueryClient();
  // The three success toasts below were already in the catalog, read by nothing
  // (#425). The three failure toasts are not, and stay English until the copy no
  // catalog message covers is migrated - see the note on `MCP_STATE_LABEL`.
  const t = useTranslations("organizations");
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const setActiveOrgId = useOrgStore((s) => s.setActiveOrgId);
  const refusedOrgIds = useOrgStore((s) => s.refusedOrgIds);

  const { data: orgs = [] } = useOrganizationList();

  // Default the active org once the list loads and nothing is selected yet -
  // preserves the behavior that used to live inside fetchOrgs, and is also what
  // settles the selection after a refused organization has been cleared.
  useEffect(() => {
    if (activeOrgId) return;
    const personal = preferredOrg(orgs, refusedOrgIds);
    if (personal) setActiveOrgId(personal.id);
  }, [activeOrgId, orgs, refusedOrgIds, setActiveOrgId]);

  const activeOrg = orgs.find((o) => o.id === activeOrgId) ?? null;

  const writeCache = useCallback(
    (updater: (prev: Organization[]) => Organization[]) =>
      queryClient.setQueryData<Organization[]>(qk.organizations.list(), (prev = []) =>
        updater(prev),
      ),
    [queryClient],
  );

  // Kept for API compatibility: the list auto-fetches on mount; this forces a
  // background refresh. The `force` arg is accepted for call-site compatibility
  // but invalidation always refetches.
  const fetchOrgs = useCallback(
    async (_force = false) => {
      await queryClient.invalidateQueries({ queryKey: qk.organizations.list() });
    },
    [queryClient],
  );

  /**
   * Create an organization, and let the caller decide how a refusal is shown.
   *
   * This used to swallow the error and toast "Failed to create organization",
   * which discarded the server's account of what was wrong - a name that is
   * too short, a slug already in use - and left nothing to put beside a field.
   */
  const createOrg = useCallback(
    async (input: CreateOrganizationInput): Promise<Organization> => {
      const org = await apiClient.post<Organization>("/orgs", input);
      writeCache((prev) => [...prev, org]);
      toast.success(t("created"));
      return org;
    },
    [writeCache, t],
  );

  const patchOrg = useCallback(
    async (id: string, patch: Partial<Pick<Organization, "name" | "avatar_url">>) => {
      try {
        const updated = await apiClient.patch<Organization>(`/orgs/${id}`, patch);
        writeCache((prev) => prev.map((o) => (o.id === id ? updated : o)));
        toast.success(t("updated"));
        return updated;
      } catch {
        toast.error(t("failedUpdate"));
        return null;
      }
    },
    [writeCache, t],
  );

  /**
   * Set the organization's monthly spending ceiling, or lift it with `null`.
   *
   * Separate from `patchOrg`, and for the same reason `createOrg` is: this one
   * can be refused with something a person can act on - a limit below what the
   * month has already spent, a role that may not change settings - and
   * `patchOrg` turns every refusal into "Failed to update organization".
   *
   * The field is always sent, including as `null`. Omitting it is how every
   * other update leaves the cap alone, so an omitted field cannot also mean
   * "remove the limit".
   */
  const setMonthlyBudget = useCallback(
    async (id: string, limitUsd: number | null): Promise<Organization> => {
      const updated = await apiClient.patch<Organization>(`/orgs/${id}`, {
        monthly_budget_usd: limitUsd,
      });
      writeCache((prev) => prev.map((o) => (o.id === id ? updated : o)));
      return updated;
    },
    [writeCache],
  );

  const deleteOrg = useCallback(
    async (id: string) => {
      try {
        await apiClient.delete(`/orgs/${id}`);
        writeCache((prev) => prev.filter((o) => o.id !== id));
        // Mirror the old store behavior: clear the active selection if it was
        // the org we just removed.
        if (useOrgStore.getState().activeOrgId === id) {
          setActiveOrgId(null);
        }
        toast.success(t("deleted"));
      } catch {
        toast.error(t("failedDelete"));
      }
    },
    [writeCache, setActiveOrgId, t],
  );

  const switchOrg = useCallback(
    (id: string) => {
      setActiveOrgId(id);
    },
    [setActiveOrgId],
  );

  return {
    orgs,
    activeOrgId,
    activeOrg,
    fetchOrgs,
    createOrg,
    patchOrg,
    setMonthlyBudget,
    deleteOrg,
    switchOrg,
  };
}
