"use client";

import { useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { TableSort } from "@/components/ui";
import { setUrlParam } from "@/lib/utils";

export interface UrlSort<K extends string> {
  by: K;
  dir: "asc" | "desc";
}

/**
 * Table sort state that survives a reload and a copied URL.
 *
 * "Sorted by cost, descending" held only in `useState` is not a thing one
 * person can send another, so the current sort is mirrored into `?sort_by=` /
 * `?sort_dir=` — the same names the backend routes take. `allowed` is the
 * column whitelist those routes declare as a `Literal`; anything else in the
 * URL falls back rather than reaching the request. A recognisable column with
 * a mangled direction keeps the column and takes the fallback's direction.
 *
 * A navigation that changes the parameters under the state wins, via the same
 * render-time adjustment `useUrlState` uses (the parameters seen last are
 * stored beside the value, and fresh ones reset it) — never an effect, which
 * would paint a stale frame first.
 *
 * A `replaceState` rather than a router push, like the tab strips beside it:
 * a sort is a view of the page, not a place Back should return through.
 */
export function useUrlSort<K extends string>(
  allowed: readonly K[],
  fallback: UrlSort<K>,
): { sort: UrlSort<K>; setSort: (next: TableSort) => void } {
  const params = useSearchParams();
  const rawBy = params.get("sort_by");
  const rawDir = params.get("sort_dir");
  const parse = (): UrlSort<K> => {
    if (!rawBy || !(allowed as readonly string[]).includes(rawBy)) return fallback;
    const dir = rawDir === "asc" || rawDir === "desc" ? rawDir : fallback.dir;
    return { by: rawBy as K, dir };
  };
  const [state, setState] = useState(() => ({ seenBy: rawBy, seenDir: rawDir, sort: parse() }));
  if (state.seenBy !== rawBy || state.seenDir !== rawDir) {
    setState({ seenBy: rawBy, seenDir: rawDir, sort: parse() });
  }
  const sort = state.seenBy === rawBy && state.seenDir === rawDir ? state.sort : parse();

  const setSort = useCallback(
    (next: TableSort) => {
      if (!(allowed as readonly string[]).includes(next.by)) return;
      setState({ seenBy: rawBy, seenDir: rawDir, sort: { by: next.by as K, dir: next.dir } });
      setUrlParam("sort_by", next.by);
      setUrlParam("sort_dir", next.dir);
    },
    // Callers pass `allowed` as a module constant; a fresh array per render
    // would remake this callback and everything memoised on it.
    [allowed, rawBy, rawDir],
  );

  return { sort, setSort };
}
