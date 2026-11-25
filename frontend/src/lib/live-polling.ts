import type { Query } from "@tanstack/react-query";

/** The `meta` key that marks a query read on an interval while its subject moves. */
const LIVE_POLLING = "livePolling";

interface PolledQuery<T> {
  state: { status: string; data: T | undefined };
}

/**
 * Options for a query read again on an interval while what it holds is still
 * moving - a run, a session, a check - spread into `useQuery`.
 *
 * TanStack Query keeps the last good answer after a failed read, so an interval
 * decided from that answer alone goes on asking a server that refuses it for as
 * long as the page is open. A failed read stops the interval here; the next
 * successful one - a retry, the live feed invalidating the query, or the person
 * coming back to the tab - starts it again. Coming back reads again only a query
 * whose last read failed, since the console leaves focus refetching off. The
 * `meta` mark is what `StaleReadBanner` looks for to tell the person the page
 * stopped updating.
 *
 * Example:
 *     useQuery({ queryKey, queryFn, ...livePolling(3000, (run) => isLive(run?.status)) })
 */
export function livePolling<T>(intervalMs: number, moving: (data: T | undefined) => boolean) {
  return {
    refetchInterval: (query: PolledQuery<T>) =>
      query.state.status !== "error" && moving(query.state.data) ? intervalMs : false,
    refetchOnWindowFocus: (query: PolledQuery<T>) => query.state.status === "error",
    meta: { [LIVE_POLLING]: true },
  };
}

/** A live-polled query on screen whose last read failed, so it shows an older answer. */
export function stoppedPolling(query: Query): boolean {
  return (
    query.meta?.[LIVE_POLLING] === true &&
    query.isActive() &&
    query.state.status === "error" &&
    query.state.data !== undefined
  );
}
