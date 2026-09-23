"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { getTable, listTables } from "@/lib/workflows/tables-api";

/** The largest page the tables route will answer (`limit: le=100`). */
const MAX_TABLES_PAGE = 100;

/**
 * The virtual tables the table + column picker offers.
 *
 * A catalog the client holds in one page and filters in the browser, like the
 * collection picker's list: an organization's tables are few enough that a round
 * trip per keystroke would be the slower design. `enabled` keeps a picker that
 * is not open — a binding still in literal mode — out of the network log.
 *
 * `error` is returned, not swallowed into an empty list: an empty catalog and a
 * refused request are the same pixels, and the picker draws a different thing for
 * each.
 */
export function useWorkflowTables(enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.tables(),
    queryFn: () => listTables({ limit: MAX_TABLES_PAGE }),
    enabled,
  });

  return {
    tables: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
  };
}

/**
 * One table and the columns of its *current* schema — what the column list is
 * scoped to, and what a bound `schema_version` is compared against to tell a
 * stale ref from a live one.
 *
 * Keyed on the table id and gated on it: a picker with no table pinned makes no
 * request. Null flows through as "nothing to fetch" rather than a bad URL.
 */
export function useWorkflowTable(tableId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.table(tableId ?? ""),
    queryFn: () => getTable(tableId as string),
    enabled: Boolean(tableId),
  });

  return {
    table: data ?? null,
    isLoading,
    error,
  };
}
