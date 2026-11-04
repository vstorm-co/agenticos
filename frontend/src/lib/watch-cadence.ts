/**
 * How often a watch may be read (#2301), as both the person's choice and the
 * organization's floor offer it: a handful of intervals, never under the fifteen
 * minutes the server allows.
 */

export const WATCH_INTERVALS = [15, 30, 60, 180, 360, 720, 1440, 10080] as const;

const HOUR = 60;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

type Translate = (key: string, values?: Record<string, number>) => string;

/** "Every 15 minutes", "Every 3 hours", "Daily", "Weekly" - `t` is the `watches.cadence` namespace. */
export function cadenceLabel(minutes: number, t: Translate): string {
  if (minutes === WEEK) return t("weekly");
  if (minutes === DAY) return t("daily");
  if (minutes % HOUR === 0) return t("everyHours", { count: minutes / HOUR });
  return t("everyMinutes", { count: minutes });
}

/** The intervals at or above a floor - what an organization's most-often allows. */
export function allowedIntervals(floor: number): number[] {
  return WATCH_INTERVALS.filter((minutes) => minutes >= floor);
}
