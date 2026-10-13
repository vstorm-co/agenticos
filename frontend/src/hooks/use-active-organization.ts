"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { localePrefixOf } from "@/lib/locale-routing";
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
 * The organization a path names, when it names one.
 *
 * `/orgs/{id}/members` and `/orgs/{id}/roles` act on the organization in their
 * URL, while every request they make carries the *active* one in
 * `X-Organization-Id` - and nothing kept the two the same: the organizations
 * list opens either page through an overlay link, where *switching* is a
 * separate button that navigates to the dashboard. So the ordinary way to reach
 * another organization's members page was the way that left the active
 * organization behind, and the page then judged Acme's members by the caller's
 * role in Globex (#1032).
 *
 * A UUID, deliberately, rather than any second segment: a later `/orgs/new`
 * would otherwise be adopted as a tenant id and refused on every request the
 * page made.
 *
 * Lower-cased, because the id is *stored*. The server serialises UUIDs in
 * canonical lower case and `activeOrg` is found by `===`, so an upper-case
 * spelling in the URL would be held as the selection, match no organization in
 * the list - the switcher then showing `orgs[0]` while requests carried another
 * tenant - and be unrecoverable, since `refusesOrganization` compares the same
 * two strings.
 *
 * The prefix is tolerated because this reads `next/navigation`'s pathname, which
 * keeps one: `/pl/orgs/{id}/members` names the same organization as
 * `/orgs/{id}/members`. Reading rather than navigating, so the rule against
 * reaching for that module holds - it is about switching locale, which loses the
 * cookie.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function organizationInPath(pathname: string): string | null {
  const segments = pathname.split("/").filter(Boolean);
  const start = localePrefixOf(pathname) === null ? 0 : 1;
  if (segments[start] !== "orgs") return null;
  const id = segments[start + 1];
  return id !== undefined && UUID.test(id) ? id.toLowerCase() : null;
}

/**
 * The organization a link *carries*, for a page whose path names none.
 *
 * Every alert email opens a page that acts on whichever organization the reader
 * last used - `apiClient` stamps `X-Organization-Id` from a selection persisted
 * per browser - and none of those URLs said which organization the alert was
 * about. So somebody in two organizations who was last working in Globex opened
 * the approval alert for a run in Acme and read Globex's queue: very likely
 * empty, and reading as "nothing is waiting" about a run that is parked and
 * ageing out (#1204).
 *
 * The same rule as the path's, for the same reasons: a UUID only, so a future
 * `?org=new` is not adopted as a tenant id and refused on every request; and
 * lower-cased, because the value is *stored* and found by `===` against ids the
 * server serialises in canonical lower case.
 */
export function organizationInQuery(search: URLSearchParams): string | null {
  const id = search.get("org");
  return id !== null && UUID.test(id) ? id.toLowerCase() : null;
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
  const t = useTranslations("organizations");
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const refusedOrgIds = useOrgStore((state) => state.refusedOrgIds);
  const setActiveOrgId = useOrgStore((state) => state.setActiveOrgId);
  const markOrgRefused = useOrgStore((state) => state.markOrgRefused);
  const { error } = usePermissions();
  const { data: orgs } = useOrganizationList();
  const pathname = usePathname();
  const search = useSearchParams();
  // The path wins. `/orgs/{id}` *is* that organization, where `?org=` is a link
  // saying which one it was about - so a query parameter cannot override the
  // page a reader is standing on.
  const named = organizationInPath(pathname) ?? organizationInQuery(search);
  // A refused organization is not adopted from a URL either, or opening its
  // page would hand the selection straight back to the one the recovery below
  // has just moved off - the shape an infinite switch loop takes.
  const adopted = named !== null && !refusedOrgIds.includes(named) ? named : null;

  /**
   * A page that names an organization *is* that organization.
   *
   * A **layout effect**, and before the queries: the API client stamps
   * `X-Organization-Id` when a request is made, and react-query starts one from
   * a passive effect - which runs after every layout effect in the commit. So
   * the selection is already the URL's by the time the page asks anything, and
   * this component is rendered before `{children}` in the dashboard layout,
   * which is what puts it before the page's own effects rather than beside them.
   *
   * **Once per path, not once per change of selection.** Keyed on the selection,
   * this wrote back whatever else moved it: the organization switcher sets the
   * id and does not navigate, so on `/orgs/{B}/members` the store went to A and
   * was snapped to B before the menu had closed - the product's primary switcher,
   * inoperative on two pages, silently. Adoption is what a *navigation* means;
   * `OrgSwitcher` handles the other direction by taking the scoped route with it.
   */
  const adoptedFor = useRef<string | null>(null);
  // The path *and* what was adopted from it, because `?org=` does not change the
  // path: two alerts about two organizations open the same page, and keying on
  // the path alone would leave the second reading the first one's tenant.
  const arrival = `${pathname}#${adopted ?? ""}`;
  useLayoutEffect(() => {
    // A URL that names no organization forgets the last one that did. The
    // dashboard layout outlives every navigation inside it, so without this a
    // reader who opened an alert, switched organization deliberately, went
    // somewhere else and came back with Back would arrive at the same URL with
    // the marker still set - reading the alert under the organization they
    // switched to.
    if (adopted === null) {
      adoptedFor.current = null;
      return;
    }
    if (arrival === adoptedFor.current) return;
    adoptedFor.current = arrival;
    if (adopted !== activeOrgId) setActiveOrgId(adopted);
  }, [adopted, activeOrgId, arrival, setActiveOrgId]);

  // Whatever moved the selection - the switcher, the URL above, or the recovery
  // below - the cache follows it. The URL's organization is passed rather than
  // the stored one so that a direct load of another organization's page records
  // *it* as the tenant the cache belongs to: the reset would otherwise fire one
  // commit later, cancelling the requests the page had already started.
  useTenantCacheReset(adopted ?? activeOrgId);

  useEffect(() => {
    if (activeOrgId === null || orgs === undefined) return;
    if (!refusesOrganization(error, activeOrgId)) return;

    markOrgRefused(activeOrgId);
    const replacement = preferredOrg(orgs, [...refusedOrgIds, activeOrgId]);
    setActiveOrgId(replacement?.id ?? null);

    // Which organization it was about, when a link named one. Somebody following
    // an alert into a tenant they have since left would otherwise be moved
    // silently and read another organization's page as the answer to it - the
    // reason the id is in the URL in the first place (#1204). The name is not
    // available: they are not a member, so it is not in their list.
    const fromLink = adopted === activeOrgId;
    toast.error(
      fromLink
        ? replacement
          ? t("accessLostLinkSwitched", { name: replacement.name })
          : t("accessLostLink")
        : replacement
          ? t("accessLostSwitched", { name: replacement.name })
          : t("accessLost"),
    );
  }, [
    error,
    activeOrgId,
    adopted,
    orgs,
    refusedOrgIds,
    markOrgRefused,
    setActiveOrgId,
    queryClient,
    t,
  ]);
}
