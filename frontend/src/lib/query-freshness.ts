import { keepPreviousData } from "@tanstack/react-query";

/** How long a dashboard card's answer is reused before a look at the page asks again. */
export const DASHBOARD_STALE_MS = 30 * 60 * 1000;

/**
 * The freshness a dashboard card needs, as one object every such query spreads.
 *
 * Thirty minutes, because what moves on a dashboard is already pushed: a run,
 * an approval, an agent or a connection changed anywhere arrives on the live
 * feed, which marks its queries stale and refetches the ones on screen. What the
 * feed does not carry - the usage and spend aggregates - is reused for half an
 * hour. A card asked again on every focus and every visit cost the page about
 * thirty requests each time somebody came back to the tab (#2248).
 *
 * `refetchOnWindowFocus` still matters: React Query refetches on focus only once
 * a query is stale, so a tab left open past the half hour catches up when it is
 * looked at rather than on a full reload.
 */
export const DASHBOARD_FRESHNESS = {
  refetchOnWindowFocus: true,
  staleTime: DASHBOARD_STALE_MS,
  // Hold the last answer while the next one is in flight.
  //
  // A period change is a new query key, so without this `isLoading` is true and
  // ten cards drop to skeletons at once - the page blanks, reflows, and comes
  // back. That is the "skeleton flash on refetch" every dashboard guide names,
  // and the fix is the same everywhere: keep the previous render, mark it as
  // stale, swap the numbers when they arrive. `UsageBody` dims what it is
  // holding so the staleness is visible rather than silently wrong.
  placeholderData: keepPreviousData,
} as const;
