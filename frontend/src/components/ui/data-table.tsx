"use client";

import { useMemo, useState, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { SortButton } from "@/components/ui/sort-button";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

export interface Column<T> {
  /** Stable key for the column. Server-side sorting and filtering send it as-is. */
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  /** Extra classes for the <td>/<th> (e.g. width, hidden on mobile). */
  className?: string;
  /**
   * Hide this column below the given breakpoint so low-priority columns
   * collapse on small screens instead of forcing horizontal scroll.
   * Omit to keep the column always visible.
   */
  hideBelow?: "sm" | "md" | "lg";
  /**
   * Renders the header as a sort control. With `onSort` on the table the click
   * is the caller's (server-side sorting); without it the table sorts the rows
   * it holds, which needs `sortValue`.
   */
  sortable?: boolean;
  /**
   * What this column sorts rows by when the table sorts client-side. A null
   * sorts last in both directions: a run with no duration yet has no place on
   * a fast-to-slow scale, which is a different fact from having been fast.
   */
  sortValue?: (row: T) => string | number | null;
  /** Draws a filter control in a second header row. */
  filter?: "text" | "select";
  /** The choices a `"select"` filter offers. Labels are the caller's copy. */
  filterOptions?: { value: string; label: string }[];
  /**
   * What a client-side filter matches against — substring for `"text"`,
   * equality for `"select"`. With `onFilter` on the table the matching is the
   * server's and this is not read.
   */
  filterValue?: (row: T) => string;
}

export interface TableSort {
  by: string;
  dir: "asc" | "desc";
}

/** Tailwind classes that hide a column until the given breakpoint. */
const hideBelowClass = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
} as const;

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  getRowKey: (row: T, index: number) => string;
  loading?: boolean;
  /** Shown when not loading and rows is empty. */
  empty?: ReactNode;
  /**
   * Shown instead of the empty state when the request failed.
   *
   * Without it, a query that answered 502 and a collection with nothing in it
   * render the same pixels — and "no runs yet" is a far more reassuring sentence
   * than the truth. That is a live defect on another page (#32), and the reason
   * this is a separate prop rather than something a caller folds into `empty`:
   * a caller that has to remember is a caller that will not.
   */
  error?: ReactNode;
  onRowClick?: (row: T) => void;
  /** Number of skeleton rows while loading. */
  skeletonRows?: number;
  className?: string;
  /** The current sort when the server sorts. Owned by the caller, shown here. */
  sort?: TableSort;
  /**
   * Asked to sort — the table computes the next state (same column flips, a new
   * column starts descending) and hands it over whole, so no caller writes its
   * own toggle reducer again. Omit to sort client-side via `sortValue`.
   */
  onSort?: (sort: TableSort) => void;
  /** Where client-side sorting starts. Ignored when `onSort` is given. */
  defaultSort?: TableSort;
  /** Current filter values by column key when the server filters. */
  filters?: Record<string, string>;
  /** Asked to filter. Omit to filter client-side via `filterValue`. */
  onFilter?: (key: string, value: string) => void;
}

const alignClass = { left: "text-left", right: "text-right", center: "text-center" } as const;

function compare(a: string | number | null, b: string | number | null, dir: "asc" | "desc") {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  const order =
    typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
  return dir === "asc" ? order : -order;
}

/**
 * Flat, theme-aware table with built-in loading, empty and error states,
 * sortable headers and per-column filters — the one table primitive (#139).
 *
 * Two modes for sorting and filtering, because the two kinds of list in this
 * product are genuinely different: a list the client holds whole is this
 * component's problem (`sortValue`/`filterValue`), and a list the server pages
 * is a request (`sort`/`onSort`, `filters`/`onFilter`) — a client-side sort of
 * page one, on a list with three pages, is worse than no header.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  loading,
  empty,
  error,
  onRowClick,
  skeletonRows = 6,
  className,
  sort,
  onSort,
  defaultSort,
  filters,
  onFilter,
}: DataTableProps<T>) {
  const t = useTranslations("ui");
  const [clientSort, setClientSort] = useState<TableSort | null>(defaultSort ?? null);
  const [clientFilters, setClientFilters] = useState<Record<string, string>>({});

  const serverSorted = onSort !== undefined;
  const activeSort = serverSorted ? (sort ?? null) : clientSort;
  const serverFiltered = onFilter !== undefined;
  const activeFilters = serverFiltered ? (filters ?? {}) : clientFilters;
  const hasFilterRow = columns.some((col) => col.filter !== undefined);

  const requestSort = (key: string) => {
    const next: TableSort =
      activeSort?.by === key
        ? { by: key, dir: activeSort.dir === "asc" ? "desc" : "asc" }
        : { by: key, dir: "desc" };
    if (onSort) onSort(next);
    else setClientSort(next);
  };

  const requestFilter = (key: string, value: string) => {
    if (onFilter) onFilter(key, value);
    else setClientFilters((current) => ({ ...current, [key]: value }));
  };

  const visible = useMemo(() => {
    if (!rows) return rows;
    let result = rows;
    if (!serverFiltered) {
      for (const col of columns) {
        const needle = clientFilters[col.key]?.trim().toLowerCase();
        if (!needle || !col.filter || !col.filterValue) continue;
        const read = col.filterValue;
        result = result.filter((row) =>
          col.filter === "select"
            ? read(row).toLowerCase() === needle
            : read(row).toLowerCase().includes(needle),
        );
      }
    }
    if (!serverSorted && clientSort) {
      const col = columns.find((entry) => entry.key === clientSort.by);
      const read = col?.sortValue;
      if (read) result = [...result].sort((a, b) => compare(read(a), read(b), clientSort.dir));
    }
    return result;
  }, [rows, columns, serverFiltered, clientFilters, serverSorted, clientSort]);

  // A failure wins over emptiness, because a failed request has no rows either
  // and would otherwise be drawn as a collection with nothing in it.
  const showError = !loading && error != null;
  const showEmpty = !loading && !showError && visible && visible.length === 0;

  return (
    <div className={cn("border-border bg-card overflow-hidden rounded-xl border", className)}>
      <div className="scrollbar-thin overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-border border-b">
              {columns.map((col) => {
                const sorted = activeSort?.by === col.key ? activeSort : null;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={
                      sorted ? (sorted.dir === "asc" ? "ascending" : "descending") : undefined
                    }
                    className={cn(
                      "text-muted-foreground px-4 py-2.5 font-mono text-[11px] font-medium tracking-wider uppercase",
                      alignClass[col.align ?? "left"],
                      col.hideBelow && hideBelowClass[col.hideBelow],
                      col.className,
                    )}
                  >
                    {col.sortable ? (
                      <SortButton
                        active={sorted !== null}
                        direction={sorted?.dir ?? "desc"}
                        onClick={() => requestSort(col.key)}
                      >
                        {col.header}
                      </SortButton>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
            {hasFilterRow && (
              <tr className="border-border border-b">
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "px-4 py-1.5",
                      col.hideBelow && hideBelowClass[col.hideBelow],
                      col.className,
                    )}
                  >
                    {col.filter === "text" && (
                      <Input
                        value={activeFilters[col.key] ?? ""}
                        onChange={(event) => requestFilter(col.key, event.target.value)}
                        aria-label={t("filterColumn")}
                        placeholder={t("filterColumn")}
                        className="h-8"
                      />
                    )}
                    {col.filter === "select" && (
                      // Native rather than the Radix Select: an empty value has
                      // to mean "no filter", which Radix items refuse to carry.
                      <select
                        value={activeFilters[col.key] ?? ""}
                        onChange={(event) => requestFilter(col.key, event.target.value)}
                        aria-label={t("filterColumn")}
                        className="border-input focus-visible:ring-ring h-8 w-full rounded-md border bg-transparent px-2 text-sm font-normal normal-case focus-visible:ring-1 focus-visible:outline-none"
                      >
                        <option value="">{t("filterAny")}</option>
                        {col.filterOptions?.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: skeletonRows }).map((_, i) => (
                <tr key={`sk-${i}`} className="border-border/60 border-b last:border-0">
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        "px-4 py-3",
                        col.hideBelow && hideBelowClass[col.hideBelow],
                        col.className,
                      )}
                    >
                      <div className="bg-foreground/10 h-4 w-2/3 animate-pulse rounded" />
                    </td>
                  ))}
                </tr>
              ))}

            {!loading &&
              visible?.map((row, i) => (
                <tr
                  key={getRowKey(row, i)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-border/60 border-b transition-colors last:border-0",
                    onRowClick && "hover:bg-accent cursor-pointer",
                  )}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        "text-foreground px-4 py-3",
                        alignClass[col.align ?? "left"],
                        col.hideBelow && hideBelowClass[col.hideBelow],
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {showError && (
        <div className="text-destructive px-4 py-12 text-center text-sm" role="alert">
          {error}
        </div>
      )}

      {showEmpty && (
        <div className="text-muted-foreground px-4 py-12 text-center text-sm">
          {empty ?? t("noResults")}
        </div>
      )}
    </div>
  );
}
