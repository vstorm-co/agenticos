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
 * URL falls back rather than reaching the request.
 *
 * A `replaceState` rather than a router push, like the tab strips beside it:
 * a sort is a view of the page, not a place Back should return through.
 */
export function useUrlSort<K extends string>(
  allowed: readonly K[],
  fallback: UrlSort<K>,
): { sort: UrlSort<K>; setSort: (next: TableSort) => void } {
  const params = useSearchParams();
  const [sort, setSortState] = useState<UrlSort<K>>(() => {
    const by = params.get("sort_by");
    const dir = params.get("sort_dir");
    if (!by || !(allowed as readonly string[]).includes(by)) return fallback;
    return { by: by as K, dir: dir === "asc" ? "asc" : "desc" };
  });

  const setSort = useCallback(
    (next: TableSort) => {
      if (!(allowed as readonly string[]).includes(next.by)) return;
      setSortState({ by: next.by as K, dir: next.dir });
      setUrlParam("sort_by", next.by);
      setUrlParam("sort_dir", next.dir);
    },
    // Callers pass `allowed` as a module constant; a fresh array per render
    // would remake this callback and everything memoised on it.
    [allowed],
  );

  return { sort, setSort };
}
