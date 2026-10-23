import type { CostByDay } from "@/types/runs";

/** One bar: the day it is, as the caller labels it, and what was spent on it. */
export interface SpendPoint {
  label: string;
  value: number;
}

const DAY_MS = 86_400_000;

/** The UTC calendar day of an instant, as `YYYY-MM-DD` - what `by_day` keys on. */
function dayKey(instant: number): string {
  return new Date(instant).toISOString().slice(0, 10);
}

/**
 * Every day of a window, each with what was spent on it - zero where nothing ran.
 *
 * `GET /spend` answers only the days that had runs, and bars drawn from those
 * alone close every gap: a quiet week vanishes and the chart claims a steady
 * habit. So the window is walked a UTC day at a time, the same days the server
 * grouped on.
 */
export function dailySpend(
  days: readonly CostByDay[],
  from: string,
  to: string | null,
  now: Date,
  label: (day: Date) => string,
): SpendPoint[] {
  const spent = new Map(days.map((entry) => [entry.day, Number(entry.cost_usd)]));
  const start = Date.parse(`${dayKey(Date.parse(from))}T00:00:00Z`);
  const end = Date.parse(`${dayKey(to === null ? now.getTime() : Date.parse(to))}T00:00:00Z`);
  const points: SpendPoint[] = [];
  for (let instant = start; instant <= end; instant += DAY_MS) {
    points.push({ label: label(new Date(instant)), value: spent.get(dayKey(instant)) ?? 0 });
  }
  return points;
}
