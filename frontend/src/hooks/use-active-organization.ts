"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { usePermissions } from "@/hooks/use-permissions";
import { preferredOrg, useOrganizationList } from "@/hooks/use-organizations";
import { ApiError } from "@/lib/api-client";
import { useOrgStore } from "@/stores";

/**
 * Whether `failure` is the server saying it will not serve `activeOrgId`.
 *
 * The distinction this makes is the whole point of the recovery. Reassigning
 * somebody's organization is destructive enough that it must happen only on a
 * refusal that is *about* that organization — never on a 500, never on a
 * dropped connection, and never on a 404 about something else. Three things
 * have to line up:
 *
 * - it is an `ApiError`, so a network failure (which throws a `TypeError` out
 *   of `fetch` and carries no status at all) can never qualify;
 * - the status is 404, which `/me/permissions` produces for exactly one reason:
 *   it takes no path parameter and loads no row, so nothing else there can go
 *   missing. `tests/api/test_stale_organization.py` pins that;
 * - the refusal names the same organization we are holding. A response about a
 *   previous selection — a request already in flight when the user switched —
 *   says nothing about the current one.
 */
export function refusesOrganization(failure: unknown, activeOrgId: string | null): boolean {
  if (activeOrgId === null) return false;
  if (!(failure instanceof ApiError) || failure.status !== 404) return false;
  return failure.details?.org_id === activeOrgId;
}

/**
 * Detect an active organization the server will not serve, and move off it.
 *
 * The persisted selection outlives the thing it names. An organization gets
 * deleted, or — the case that will keep happening in a multi-tenant product —
 * somebody is removed from one while they are signed in, and the id in
 * `localStorage` goes on being sent as `X-Organization-Id` on every request.
 * The server is right to refuse it. What was wrong was the consequence:
 * `usePermissions().can()` answers false whenever permissions are unavailable,
 * which is correct for the second it takes to load them and indefensible when
 * they never arrive — the sidebar quietly lost Agents, Skills, Activity,
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
 *   a dozen components at once — putting the recovery there fires it a dozen
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

  useEffect(() => {
    if (activeOrgId === null || orgs === undefined) return;
    if (!refusesOrganization(error, activeOrgId)) return;

    markOrgRefused(activeOrgId);
    const replacement = preferredOrg(orgs, [...refusedOrgIds, activeOrgId]);
    setActiveOrgId(replacement?.id ?? null);

    // Everything cached was read as the organization we just left. Refetching
    // is not a nicety: leaving it would show one organization's agents under
    // another's name until something happened to invalidate them.
    queryClient.invalidateQueries();

    toast.error(
      replacement
        ? `You no longer have access to that organization. Switched to ${replacement.name}.`
        : "You no longer have access to that organization.",
    );
  }, [error, activeOrgId, orgs, refusedOrgIds, markOrgRefused, setActiveOrgId, queryClient]);
}
