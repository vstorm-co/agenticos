import { keepPreviousData } from "@tanstack/react-query";

/**
 * The freshness a dashboard card needs, as one object every such query spreads.
 *
 * The app-wide defaults in `providers.tsx` hold data fresh for five minutes and
 * never refetch on focus, which is right for a page somebody is reading: moving
 * around the product should not re-ask every list. A dashboard is the opposite
 * shape - it is left open in a background tab while the person does the thing
 * the numbers are about, and comes back expecting to see it.
 *
 * **All three fields are load-bearing.** React Query refetches on focus only when a
 * query is already stale, so `refetchOnWindowFocus` on its own is a no-op for
 * the whole five minutes somebody is watching to see whether their run landed -
 * the symptom is a dashboard that only ever moves on a full page reload.
 */
export const DASHBOARD_FRESHNESS = {
  refetchOnWindowFocus: true,
  staleTime: 0,
  // The third: hold the last answer while the next one is in flight.
  //
  // A period change is a new query key, so without this `isLoading` is true and
  // ten cards drop to skeletons at once - the page blanks, reflows, and comes
  // back. That is the "skeleton flash on refetch" every dashboard guide names,
  // and the fix is the same everywhere: keep the previous render, mark it as
  // stale, swap the numbers when they arrive. `UsageBody` dims what it is
  // holding so the staleness is visible rather than silently wrong.
  placeholderData: keepPreviousData,
} as const;
