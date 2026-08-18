"use client";

import { useMemo } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import {
  AGENT_BUILDER,
  KB_DETAIL,
  ORG_MEMBERS,
  ORG_ROLES,
  SETTINGS_DETAIL,
  WORKSPACE_DETAIL,
} from "@/lib/onboarding/tour";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { AgentList } from "@/types/agents";
import type { KnowledgeBaseList } from "@/types/knowledge-base";
import type { OrganizationList } from "@/types/organization";

/**
 * The organization a path names, for the `/orgs/<id>/…` detail routes, or `null`
 * for anything else — including `/orgs` itself, which names none.
 */
function orgIdFromPath(path: string): string | null {
  const segments = path.split("/").filter(Boolean);
  return segments[0] === "orgs" && segments.length > 1 ? (segments[1] ?? null) : null;
}

/**
 * The detail pseudo-pages whose example is found by asking the server.
 *
 * `SETTINGS_DETAIL` and `WORKSPACE_DETAIL` are deliberately absent: one resolves
 * to a fixed route and the other to nothing at all, so neither costs a request.
 * A caller passes `enabled` false when the walk it is about to run names none of
 * these — a "?" on the vault has no detail stop, and fetching three lists to
 * answer a question nobody asks is three requests per press.
 */
export const FETCHED_DETAIL_PAGES: ReadonlySet<string> = new Set([
  AGENT_BUILDER,
  KB_DETAIL,
  ORG_MEMBERS,
  ORG_ROLES,
]);

/** Where a detail pseudo-page resolves to, and whether we are still finding out. */
export interface ResolvedDetail {
  /** True while the list this route is picked from is still loading. */
  pending: boolean;
  /** The concrete route to open, or null when there is nothing to open. */
  href: string | null;
}

/**
 * For each detail pseudo-page a tour step can name, the concrete route the engine
 * pushes to reach an example of it.
 *
 * A detail view has no route of its own, so the walkthrough opens a real one: the
 * seeded demo where there is one, otherwise the first row. The list is fetched
 * only while the tour is open, and a null `href` (an empty list) means there is no
 * example to open — so the engine describes the section where the reader is rather
 * than navigate to a route that would 404 (`onboarding-tour.tsx`, `show(undefined)`).
 * The "?" replayed *from* a detail route never consults this — the reader is already
 * on the row they mean, and the engine keeps them there.
 *
 * Each list is read under the same query key its owning page hook uses, so the
 * fetch is shared rather than duplicated — which means each query here must store
 * the *same shape* that hook stores, or the two observers fight over one cache
 * entry and whichever loses reads the wrong shape. `useAgents` caches the whole
 * `AgentList`; `useKnowledgeBases` and `useOrganizationList` cache the `.items`
 * array. The queries below mirror that, exactly.
 */
export function useDetailTargets(enabled: boolean): Record<string, ResolvedDetail> {
  const agents = useQuery({
    queryKey: qk.agents.list(false),
    queryFn: () => apiClient.get<AgentList>("/agents"),
    enabled,
  });
  const agentId =
    agents.data?.items.find((agent) => agent.slug === "getting-started")?.id ??
    agents.data?.items[0]?.id ??
    null;

  const kbs = useQuery({
    queryKey: qk.kb.list(),
    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,
    enabled,
  });
  const kbId = kbs.data?.find((kb) => kb.is_default)?.id ?? kbs.data?.[0]?.id ?? null;

  // The example organization is the one the reader is looking at, then the one
  // they are in, then the list (which is also what `pending` waits on). Members and
  // roles are two routes under the same org, so both resolve from the one id.
  //
  // The route comes first because the two can disagree: every card on `/orgs` links
  // straight to that organization's members without switching to it, so a "?"
  // pressed there resolved to the *active* organization and the walk's next stop
  // pushed its roles page — the help silently changing which organization it was
  // explaining, mid-walk.
  const routeOrgId = orgIdFromPath(stripLocale(usePathname()));
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const orgs = useQuery({
    queryKey: qk.organizations.list(),
    queryFn: async () => (await apiClient.get<OrganizationList>("/orgs")).items,
    enabled,
  });
  const orgId =
    routeOrgId ??
    activeOrgId ??
    orgs.data?.find((org) => org.is_personal)?.id ??
    orgs.data?.[0]?.id ??
    null;
  const orgPending = enabled && !routeOrgId && !activeOrgId && orgs.isPending;

  return useMemo(
    () => ({
      [AGENT_BUILDER]: {
        pending: enabled && agents.isPending,
        href: agentId ? ROUTES.AGENT_DETAIL(agentId) : null,
      },
      [KB_DETAIL]: {
        pending: enabled && kbs.isPending,
        href: kbId ? ROUTES.RAG_DETAIL(kbId) : null,
      },
      [ORG_MEMBERS]: {
        pending: orgPending,
        href: orgId ? ROUTES.ORG_MEMBERS(orgId) : null,
      },
      [ORG_ROLES]: {
        pending: orgPending,
        href: orgId ? ROUTES.ORG_ROLES(orgId) : null,
      },
      // Two "?"-only sections with nothing to fetch. Settings resolves to its own
      // first page for the rare navigation into it, but its stop is really shown in
      // place on whichever settings page the reader opened help from. A workspace
      // has no seeded example to open — it is a person's own agent output — so it
      // never resolves an href and is not walked into from the list; the entry
      // exists only so the engine treats it as a detail it need not navigate to.
      [SETTINGS_DETAIL]: { pending: false, href: ROUTES.SETTINGS_PROFILE },
      [WORKSPACE_DETAIL]: { pending: false, href: null },
    }),
    [enabled, agents.isPending, agentId, kbs.isPending, kbId, orgPending, orgId],
  );
}
