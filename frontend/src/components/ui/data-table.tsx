"use client";

import { useMemo, useState, type ReactNode } from "react";

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
   * it holds, which needs `sortValue` — a client-mode column without one renders
   * a plain header rather than a control that flips its arrow over rows that
   * never move.
   */
  sortable?: boolean;
  /**
   * What this column sorts rows by when the table sorts client-side. A null
   * sorts last in both directions: a run with no duration yet has no place on
   * a fast-to-slow scale, which is a different fact from having been fast.
   */
  sortValue?: (row: T) => string | number | null;
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
  /**
   * Which row is the one currently open somewhere else - a detail panel beside
   * the table, usually.
   *
   * Without it a list that opens a panel gives no answer to "which of these am I
   * looking at", and stepping through rows from inside the panel moves a
   * selection nothing on screen shows.
   */
  isRowActive?: (row: T) => boolean;
  /**
   * Fill the height its container gives it, scrolling the rows rather than the
   * page - and pinning the column headers while they scroll.
   *
   * For a list that shares the screen with something else: a wall of numbers
   * whose headers have scrolled off says nothing, and a page-level scroll takes
   * the filters and the pager with it. The header can only pin here because this
   * component owns the scroll container - the horizontal one it already had
   * becomes the vertical one too, and `sticky` resolves against it.
   */
  fillHeight?: boolean;
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
}

const alignClass = { left: "text-left", right: "text-right", center: "text-center" } as const;

function compare(a: string | number | null, b: string | number | null, dir: "asc" | "desc") {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  const order =
    typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
  return dir === "asc" ? order : -order;
}

/**
 * Flat, theme-aware table with built-in loading, empty and error states and
 * sortable headers — the one table primitive (#139).
 *
 * Two modes for sorting, because the two kinds of list in this product are
 * genuinely different: a list the client holds whole is this component's
 * problem (`sortValue`), and a list the server pages is a request
 * (`sort`/`onSort`) — a client-side sort of page one, on a list with three
 * pages, is worse than no header. Filtering deliberately lives outside: the
 * standard is a control strip inside the list card (`ListCardControlsRow`),
 * never a second header row under the columns.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  loading,
  empty,
  error,
  onRowClick,
  isRowActive,
  fillHeight = false,
  skeletonRows = 6,
  className,
  sort,
  onSort,
  defaultSort,
}: DataTableProps<T>) {
  const t = useTranslations("ui");
  const [clientSort, setClientSort] = useState<TableSort | null>(defaultSort ?? null);

  const serverSorted = onSort !== undefined;
  const activeSort = serverSorted ? (sort ?? null) : clientSort;

  const requestSort = (key: string) => {
    const next: TableSort =
      activeSort?.by === key
        ? { by: key, dir: activeSort.dir === "asc" ? "desc" : "asc" }
        : { by: key, dir: "desc" };
    if (onSort) onSort(next);
    else setClientSort(next);
  };

  const visible = useMemo(() => {
    if (!rows) return rows;
    let result = rows;
    if (!serverSorted && clientSort) {
      const col = columns.find((entry) => entry.key === clientSort.by);
      const read = col?.sortValue;
      if (read) result = [...result].sort((a, b) => compare(read(a), read(b), clientSort.dir));
    }
    return result;
  }, [rows, columns, serverSorted, clientSort]);

  // A failure wins over emptiness, because a failed request has no rows either
  // and would otherwise be drawn as a collection with nothing in it.
  const showError = !loading && error != null;
  const showEmpty = !loading && !showError && visible && visible.length === 0;

  return (
    <div
      className={cn(
        "border-border bg-card overflow-hidden rounded-xl border",
        fillHeight && "flex min-h-0 flex-1 flex-col",
        className,
      )}
    >
      <div
        className={cn(
          "scrollbar-thin overflow-x-auto",
          fillHeight && "min-h-0 flex-1 overflow-y-auto",
        )}
      >
        <table className="w-full border-collapse text-sm">
          <thead className={cn(fillHeight && "bg-card sticky top-0 z-10")}>
            <tr className="border-border border-b">
              {columns.map((col) => {
                const sortsHere = col.sortable && (serverSorted || col.sortValue !== undefined);
                const sorted = sortsHere && activeSort?.by === col.key ? activeSort : null;
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
                    {sortsHere ? (
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
                  // `aria-selected` as well as the tint, because "which row is
                  // open" is an answer a screen reader needs too, and a colour
                  // is not one.
                  aria-selected={isRowActive ? isRowActive(row) : undefined}
                  className={cn(
                    "border-border/60 border-b transition-colors last:border-0",
                    onRowClick && "hover:bg-accent cursor-pointer",
                    // A tint alone reads as hover - they were the same colour,
                    // and a reader who has moved the mouse cannot tell which row
                    // the panel beside them is showing. The rule down the left
                    // edge is the part that does not move with the cursor.
                    isRowActive?.(row) &&
                      "bg-accent hover:bg-accent shadow-[inset_2px_0_0_0_var(--color-primary)]",
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
