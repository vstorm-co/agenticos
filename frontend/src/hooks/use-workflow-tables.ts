"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { getTable, listTables } from "@/lib/tables-api";

/** The largest page the tables route will answer (`limit: le=100`). */
const MAX_TABLES_PAGE = 100;

/**
 * The virtual tables the table + column picker offers.
 *
 * A catalog the client holds whole and filters in the browser, like the
 * collection picker's list: an organization's tables are few enough that a round
 * trip per keystroke would be the slower design. The list is walked page by page
 * to its `total`, because the route caps a page at a hundred and an organization
 * may hold more: a single page left tables beyond it unpickable. `enabled` keeps a picker that
 * is not open — a binding still in literal mode — out of the network log.
 *
 * `error` is returned, not swallowed into an empty list: an empty catalog and a
 * refused request are the same pixels, and the picker draws a different thing for
 * each.
 */
export function useWorkflowTables(enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.tables(),
    queryFn: async () => {
      const first = await listTables({ skip: 0, limit: MAX_TABLES_PAGE });
      const items = [...first.items];
      while (items.length < first.total && items.length > 0) {
        const next = await listTables({ skip: items.length, limit: MAX_TABLES_PAGE });
        // An empty page ends the walk: a table removed between two requests makes
        // `total` larger than what is left to read.
        if (next.items.length === 0) break;
        items.push(...next.items);
      }
      return { items, total: first.total };
    },
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
