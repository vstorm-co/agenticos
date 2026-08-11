/**
 * The completed-share arithmetic shared by the Activity version strip and the
 * dashboard's Outcomes donut.
 *
 * Both surfaces answer one question under one word - what share of a window's
 * runs completed - and the way two screens drift apart on it is the
 * denominator: a donut that reads `cancelled` as "not a failure" and a strip
 * that reads it as "not completed" are each defensible and disagree on the same
 * rows. So the rule this module fixes, and `run-outcomes.test.ts` enforces, is
 * that nothing is excluded: `cancelled` and `budget_exceeded` sit in the
 * denominator like any other outcome, and the two surfaces read one number.
 * `docs/design/activity-plan.md` §8a.4.
 */

import type { StatusCount, VersionUsageRow } from "@/types/stats";

/** Runs that completed, over every run in the window with nothing excluded. */
export interface RunTally {
  completed: number;
  total: number;
}

/**
 * The completed share as a fraction in [0, 1], or null for an empty window.
 *
 * Null rather than zero: a share of no runs is unknown, not zero percent, and
 * a caller renders the two differently ("—" versus "0%").
 */
export function completedShare({ completed, total }: RunTally): number | null {
  return total > 0 ? completed / total : null;
}

/**
 * The donut's tally: the `completed` status count over the sum of every status.
 *
 * Summed here rather than read off `total_runs` so numerator and denominator
 * come from one place and cannot disagree; the backend's own invariant is that
 * the two are equal, since the status counts are the same rows counted twice
 * (`app/schemas/stats.py`).
 */
export function statusTally(byStatus: readonly StatusCount[]): RunTally {
  let completed = 0;
  let total = 0;
  for (const row of byStatus) {
    total += row.runs;
    if (row.status === "completed") completed += row.runs;
  }
  return { completed, total };
}

/** One version strip row's tally: its completed runs over all of its runs. */
export function versionTally(row: Pick<VersionUsageRow, "runs" | "completed_runs">): RunTally {
  return { completed: row.completed_runs, total: row.runs };
}

/**
 * A completed share as a locale-formatted whole-number percent, or a dash for
 * an empty window. Shared so the two surfaces print one string for one number.
 */
export function formatCompletedShare(share: number | null, locale?: string): string {
  if (share === null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(
    share,
  );
}
