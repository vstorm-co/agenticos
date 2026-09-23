"use client";

import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { queryRecords } from "@/lib/tables-api";
import type { RecordQuery } from "@/types/tables";

/**
 * A page of one table's records, matching the given filters/sort - the one
 * read path every view type (grid, kanban lane, list) shares. Only the layout
 * differs; the query is always `POST .../records/query`.
 */
export function useTableRecords(tableId: string | null, query: RecordQuery) {
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.tables.records(tableId ?? "", query),
    queryFn: () => queryRecords(tableId as string, query),
    enabled: !!tableId,
    placeholderData: (previous) => previous,
  });

  return {
    records: data?.items ?? [],
    hasMore: data?.has_more ?? false,
    isLoading,
    isFetching,
    error,
    refetch,
  };
}
