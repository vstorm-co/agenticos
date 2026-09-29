"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { countRecords, queryRecords } from "@/lib/tables-api";
import type { RecordCountQuery, RecordQuery } from "@/types/tables";

/** The most a query returns at once, and the furthest it may skip (`RecordQuery`'s bounds). */
const PAGE = 100;
const MAX_SKIP = 10_000;

/**
 * One table's records, a page at a time as the grid scrolls, matching the
 * given filters, search and sort.
 *
 * The service pages by offset and skips at most ten thousand records, so a
 * listing longer than that ends there: `truncated` says so, and the filters are
 * the way to reach what lies beyond.
 */
export function useTableRecordPages(
  tableId: string | null,
  query: Omit<RecordQuery, "skip" | "limit">,
) {
  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage } = useInfiniteQuery({
    queryKey: qk.tables.recordsInfinite(tableId ?? "", query),
    queryFn: ({ pageParam }) =>
      queryRecords(tableId as string, { ...query, skip: pageParam, limit: PAGE }),
    enabled: !!tableId,
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.has_more && last.skip + PAGE <= MAX_SKIP ? last.skip + PAGE : undefined,
  });
  const pages = data?.pages ?? [];
  const last = pages.at(-1);

  return {
    records: pages.flatMap((page) => page.items),
    isLoading,
    isFetchingNextPage,
    truncated: last !== undefined && last.has_more && !hasNextPage,
    /** Load the next page, unless one is loading or none is left. */
    loadMore: () => {
      if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
    },
  };
}

/** How many of one table's records match, counted by the service up to its cap. */
export function useTableRecordCount(tableId: string | null, query: RecordCountQuery) {
  const { data } = useQuery({
    queryKey: qk.tables.recordCount(tableId ?? "", query),
    queryFn: () => countRecords(tableId as string, query),
    enabled: !!tableId,
    placeholderData: (previous) => previous,
  });
  return data ?? null;
}
