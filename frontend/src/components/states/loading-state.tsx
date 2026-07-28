import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The shape a wait stands in for.
 *
 * Every variant is a skeleton, and that is deliberate: this component used to
 * default to three pulsing dots, so twelve pages showed a shapeless wait
 * because nobody passed a prop. A component whose default is its worst option
 * is a trap, so the shapeless option is gone rather than demoted. A mid-action
 * pause with no layout to promise - a submitting button, an OAuth round-trip -
 * is `Spinner`'s job, not this one's.
 */
type Variant =
  | "skeleton-list"
  | "skeleton-cards"
  | "skeleton-tiles"
  | "skeleton-table"
  | "skeleton-panel"
  | "stats";

/**
 * How many placeholders a variant shows when the caller does not say.
 *
 * A count cannot be read from the data: React Query only reports `isLoading`
 * while the cache is empty, so the `total` these hooks return arrives with the
 * rows themselves and is zero here. Failing that, these are chosen to fill
 * roughly one screen without over-promising - six cards is two rows of three at
 * 1440px, which is what the grids show first - rather than the largest number
 * that would still fit.
 */
const DEFAULT_ROWS: Record<Variant, number> = {
  "skeleton-list": 4,
  "skeleton-cards": 6,
  "skeleton-tiles": 6,
  "skeleton-table": 8,
  "skeleton-panel": 3,
  stats: 4,
};

/** Cell widths cycled across a table's columns so a row does not read as a bar. */
const CELL_WIDTHS = ["w-24", "w-16", "w-28", "w-14", "w-20", "w-12"] as const;

interface LoadingStateProps {
  /** Which shape to stand in for. Defaults to a row list. */
  variant?: Variant;
  /** Rows for a list, table or panel; cards for a grid. Defaults per variant. */
  rows?: number;
  /** Columns for `skeleton-table`. Ignored by every other variant. */
  columns?: number;
  className?: string;
}

/**
 * A placeholder shaped like the content that is about to replace it.
 *
 * Pick the variant that matches what the page renders, and pass `className` to
 * reconcile the last difference - the grid variants' column counts are merged
 * by `cn`, so a two-up page passes `lg:grid-cols-2` instead of getting a
 * variant of its own.
 *
 * Motion is a plain `animate-pulse`. `globals.css` already flattens every
 * animation under `prefers-reduced-motion: reduce`, so these settle to a static
 * grey at full opacity there and nothing extra is needed per element.
 */
export function LoadingState({
  variant = "skeleton-list",
  rows,
  columns = 5,
  className,
}: LoadingStateProps) {
  const count = rows ?? DEFAULT_ROWS[variant];

  switch (variant) {
    case "skeleton-list":
      return <RowList count={count} className={className} />;
    case "skeleton-cards":
      return <CardGrid count={count} className={className} />;
    case "skeleton-tiles":
      return <TileGrid count={count} className={className} />;
    case "skeleton-table":
      return <Table rows={count} columns={columns} className={className} />;
    case "skeleton-panel":
      return <Panel rows={count} className={className} />;
    case "stats":
      return <Stats count={count} className={className} />;
  }
}

/**
 * One placeholder bar. `bg-foreground/10` is the primary tone and
 * `bg-foreground/8` the secondary one; `cn` lets a caller swap either.
 */
function Bar({ className }: { className?: string }) {
  return <div className={cn("bg-foreground/10 animate-pulse rounded", className)} />;
}

/**
 * The announced wrapper. One `role="status"` per skeleton, so a screen reader
 * hears "Loading" once instead of narrating twenty decorative bars.
 */
function Shell({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div role="status" aria-label="Loading" className={className}>
      {children}
    </div>
  );
}

/** Keys for a fixed-length placeholder run - index is the only identity there is. */
function keys(count: number): number[] {
  return Array.from({ length: count }, (_, i) => i);
}

/** Bordered rows with a leading icon square. Vault, integrations, activity lists. */
function RowList({ count, className }: { count: number; className?: string }) {
  return (
    <Shell className={cn("space-y-3", className)}>
      {keys(count).map((i) => (
        <div
          key={i}
          className="border-border bg-card flex items-center gap-3 rounded-xl border p-4"
        >
          <Bar className="h-9 w-9 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Bar className="h-3 w-1/3" />
            <Bar className="bg-foreground/8 h-3 w-2/3" />
          </div>
        </div>
      ))}
    </Shell>
  );
}

/** Grid of text cards - name, slug, status badge, two lines. Agents, skills, MCP servers. */
function CardGrid({ count, className }: { count: number; className?: string }) {
  return (
    <Shell className={cn("grid gap-3 sm:grid-cols-2 xl:grid-cols-3", className)}>
      {keys(count).map((i) => (
        <div key={i} className="border-border bg-card space-y-3 rounded-xl border p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              <Bar className="h-3.5 w-1/2" />
              <Bar className="bg-foreground/8 h-3 w-1/3" />
            </div>
            <Bar className="h-5 w-16 shrink-0 rounded-full" />
          </div>
          <Bar className="bg-foreground/8 h-3 w-full" />
          <Bar className="bg-foreground/8 h-3 w-4/5" />
        </div>
      ))}
    </Shell>
  );
}

/** Grid of taller cards led by an icon tile, closed by a footer row. Knowledge bases, organizations. */
function TileGrid({ count, className }: { count: number; className?: string }) {
  return (
    <Shell className={cn("grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}>
      {keys(count).map((i) => (
        <div key={i} className="border-border bg-card flex flex-col rounded-xl border p-5">
          <div className="flex items-start justify-between gap-2">
            <Bar className="h-9 w-9 shrink-0 rounded-lg" />
            <Bar className="h-5 w-14 rounded-full" />
          </div>
          <div className="mt-4 flex-1 space-y-2">
            <Bar className="h-4 w-2/3" />
            <Bar className="bg-foreground/8 h-3 w-full" />
          </div>
          <div className="mt-5 flex items-center justify-between gap-2">
            <Bar className="bg-foreground/8 h-3 w-1/3" />
            <Bar className="bg-foreground/8 h-3.5 w-3.5" />
          </div>
        </div>
      ))}
    </Shell>
  );
}

/** Header row plus body rows at the caller's column count. Run history, the permission matrix. */
function Table({
  rows,
  columns,
  className,
}: {
  rows: number;
  columns: number;
  className?: string;
}) {
  const cols = keys(columns);

  return (
    <Shell className={cn("overflow-x-auto", className)}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            {cols.map((col) => (
              <th key={col} className="px-3 py-2 first:pl-0">
                <Bar className="h-3 w-16" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys(rows).map((row) => (
            <tr key={row} className="border-b last:border-0">
              {cols.map((col) => (
                <td key={col} className="px-3 py-3 first:pl-0">
                  <Bar
                    className={cn("bg-foreground/8 h-3", CELL_WIDTHS[col % CELL_WIDTHS.length])}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  );
}

/** A card with a title, a description and inner rows. Sharing, availability, the skill editor. */
function Panel({ rows, className }: { rows: number; className?: string }) {
  return (
    <Shell className={cn("bg-card space-y-4 rounded-xl border p-6 shadow", className)}>
      <div className="space-y-2">
        <Bar className="h-4 w-1/4" />
        <Bar className="bg-foreground/8 h-3 w-3/4" />
      </div>
      <div className="space-y-2">
        {keys(rows).map((i) => (
          <div key={i} className="space-y-2 rounded-md border p-3">
            <Bar className="h-3 w-1/3" />
            <Bar className="bg-foreground/8 h-3 w-1/2" />
          </div>
        ))}
      </div>
    </Shell>
  );
}

/** Stat tiles - label, figure, sparkline slot. Admin dashboards, activity totals. */
function Stats({ count, className }: { count: number; className?: string }) {
  return (
    <Shell className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {keys(count).map((i) => (
        <div key={i} className="border-border bg-card space-y-3 rounded-xl border p-5">
          <Bar className="h-3 w-2/5" />
          <Bar className="bg-foreground/15 h-8 w-1/2 rounded-md" />
          <Bar className="bg-foreground/8 h-10 w-full rounded-md" />
        </div>
      ))}
    </Shell>
  );
}
