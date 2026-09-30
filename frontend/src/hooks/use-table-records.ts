"use client";

import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { queryRecords } from "@/lib/tables-api";
import { useTableViewStore } from "@/stores/table-view-store";
import type { RecordQuery } from "@/types/tables";

/**
 * A page of one table's records, matching the given filters/sort - the one
 * read path every view type (grid, kanban lane, list) shares. Only the layout
 * differs; the query is always `POST .../records/query`.
 */
export function useTableRecords(tableId: string | null, query: RecordQuery) {
  const { data, isLoading, isFetching, isPlaceholderData, error, refetch } = useQuery({
    queryKey: qk.tables.records(tableId ?? "", query),
    queryFn: () => queryRecords(tableId as string, query),
    enabled: !!tableId,
    placeholderData: (previous) => previous,
  });

  // A record waiting out its delete's undo window is already gone from view.
  const deleting = useTableViewStore((state) => state.deleting);
  return {
    records: (data?.items ?? []).filter((record) => !deleting[record.id]),
    hasMore: data?.has_more ?? false,
    isLoading,
    isFetching,
    /** The previous query's page, standing in while this one loads. */
    isPlaceholderData,
    error,
    refetch,
  };
}
