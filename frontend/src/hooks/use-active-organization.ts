"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { usePermissions } from "@/hooks/use-permissions";
import { preferredOrg, useOrganizationList } from "@/hooks/use-organizations";
import { ApiError } from "@/lib/api-client";
import { resetTenantState, useOrgStore } from "@/stores";

/**
 * Whether `failure` is the server saying it will not serve `activeOrgId`.
 *
 * The distinction this makes is the whole point of the recovery. Reassigning
 * somebody's organization is destructive enough that it must happen only on a
 * refusal that is *about* that organization - never on a 500, never on a
 * dropped connection, and never on a 404 about something else. Three things
 * have to line up:
 *
 * - it is an `ApiError`, so a network failure (which throws a `TypeError` out
 *   of `fetch` and carries no status at all) can never qualify;
 * - the status is 404, which `/me/permissions` produces for exactly one reason:
 *   it takes no path parameter and loads no row, so nothing else there can go
 *   missing. `tests/api/test_stale_organization.py` pins that;
 * - the refusal names the same organization we are holding. A response about a
 *   previous selection - a request already in flight when the user switched -
 *   says nothing about the current one.
 */
export function refusesOrganization(failure: unknown, activeOrgId: string | null): boolean {
  if (activeOrgId === null) return false;
  if (!(failure instanceof ApiError) || failure.status !== 404) return false;
  return failure.details?.org_id === activeOrgId;
}

/**
 * Drop everything read as the previous organization when the tenant changes.
 *
 * Most query keys do not name the organization - `agents.list()`,
 * `kb.list()`, `skills.list()`, `secrets.list()` and the rest are the same key
 * whichever tenant is active - so without this, switching organization changes
 * a label in the header and nothing else. With `staleTime` at five minutes and
 * `refetchOnWindowFocus` off, the previous tenant's agent names, knowledge
 * bases and secrets stay on screen for as long as the cache holds them, with
 * no request in flight to correct them.
 *
 * `removeQueries`, not `invalidateQueries`. Invalidating marks a query stale
 * and refetches it, but React Query serves the cached rows meanwhile - so the
 * previous tenant's names are still painted, just briefly. Between "briefly"
 * and "not at all", a multi-tenant product picks the second.
 *
 * A **layout effect**, for the same reason. The switcher sets the id and React
 * renders the new organization's name at once; a passive effect runs after that
 * render has been painted, so the previous tenant's rows appear under the new
 * name for a frame. A layout effect runs after the commit and before the paint.
 *
 * It costs a refetch of the deployment-wide catalogs too - model profiles, the
 * capability catalog, the skill library - which are the same answer for every
 * tenant. That is the price of one guard instead of eleven key signatures,
 * each of which is a place the next key can forget.
 *
 * **The comparison is on the tenant, not on the selection.** `activeOrgId` is
 * null until the list loads and the default is picked, and a request made
 * meanwhile carries no `X-Organization-Id` - which the backend reads as the
 * caller's personal organization, not as no organization at all. So null and
 * the personal org's id are the same tenant, and treating the first resolution
 * as a switch dropped the queries a freshly loaded page had just started. The
 * seed's "a provider key is stored" caught that: the secret was created and
 * the list that should have shown it never arrived.
 */
function useTenantCacheReset(activeOrgId: string | null): void {
  const queryClient = useQueryClient();
  const { data: orgs } = useOrganizationList();
  const personalId = orgs?.find((org) => org.is_personal)?.id ?? null;
  const tenant = activeOrgId ?? personalId;
  const cacheBelongsTo = useRef<string | null>(null);

  useLayoutEffect(() => {
    // Nothing has identified the tenant yet - no selection, and no list to
    // resolve the personal organization from. Anything cached now is cached
    // under whoever this turns out to be.
    if (tenant === null) return;
    const previous = cacheBelongsTo.current;
    cacheBelongsTo.current = tenant;
    // The first tenant this page identifies is the one its cache already
    // belongs to; there is nothing to drop, and dropping it would cancel the
    // queries the page started before the organization list came back.
    if (previous !== null && previous !== tenant) {
      queryClient.removeQueries();
      // The cache is not all of it. Conversations, the chat transcript, the
      // open preview and the sources behind the last answer are module-scope
      // stores, which `removeQueries` cannot reach - and every one of them
      // belongs to the organization just left.
      resetTenantState();
    }
  }, [tenant, queryClient]);
}

/**
 * Detect an active organization the server will not serve, and move off it.
 *
 * The persisted selection outlives the thing it names. An organization gets
 * deleted, or - the case that will keep happening in a multi-tenant product -
 * somebody is removed from one while they are signed in, and the id in
 * `localStorage` goes on being sent as `X-Organization-Id` on every request.
 * The server is right to refuse it. What was wrong was the consequence:
 * `usePermissions().can()` answers false whenever permissions are unavailable,
 * which is correct for the second it takes to load them and indefensible when
 * they never arrive - the sidebar quietly lost Agents, Skills, Activity,
 * Knowledge bases, RAG search, providers and MCP servers, with no error and no
 * route back short of knowing to open the organization switcher.
 *
 * Recovery belongs here rather than in the store, the API client or
 * `usePermissions`:
 *
 * - the **store** cannot fetch, and choosing a replacement means knowing which
 *   organizations the caller actually belongs to;
 * - the **API client** sees every refusal, which sounds like the right vantage
 *   point until you need to tell a missing agent's 404 from a missing
 *   organization's. It also runs outside React, with no query cache to
 *   invalidate and no orgs list to fall back to;
 * - **`usePermissions`** is where the refusal is visible, but it is rendered by
 *   a dozen components at once - putting the recovery there fires it a dozen
 *   times for one failure.
 *
 * So: one hook, mounted once, by one component. It reads the permissions query
 * that every page already runs, and does nothing at all until that query is
 * refused for this organization specifically.
 */
export function useActiveOrganizationRecovery(): void {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const refusedOrgIds = useOrgStore((state) => state.refusedOrgIds);
  const setActiveOrgId = useOrgStore((state) => state.setActiveOrgId);
  const markOrgRefused = useOrgStore((state) => state.markOrgRefused);
  const { error } = usePermissions();
  const { data: orgs } = useOrganizationList();

  // Whatever moved the selection - the switcher, the recovery below, or a
  // path that does not exist yet - the cache follows it.
  useTenantCacheReset(activeOrgId);

  useEffect(() => {
    if (activeOrgId === null || orgs === undefined) return;
    if (!refusesOrganization(error, activeOrgId)) return;

    markOrgRefused(activeOrgId);
    const replacement = preferredOrg(orgs, [...refusedOrgIds, activeOrgId]);
    setActiveOrgId(replacement?.id ?? null);

    toast.error(
      replacement
        ? `You no longer have access to that organization. Switched to ${replacement.name}.`
        : "You no longer have access to that organization.",
    );
  }, [error, activeOrgId, orgs, refusedOrgIds, markOrgRefused, setActiveOrgId, queryClient]);
}
