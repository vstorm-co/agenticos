/**
 * The dashboard's time filter: presets and custom ranges, one shape.
 *
 * Every preset reduces to an inclusive `from`/`to` pair of ISO dates - the
 * API has one time parameter, not two kinds. All arithmetic is UTC, matching
 * the backend's bucketing, so the filter and the chart agree on what "today"
 * contains. The URL form is either a preset id (`period=7d`) or the range
 * itself (`period=2026-07-05..2026-07-20`), so a custom range survives a
 * page reload and a pasted link.
 */

export type PeriodPreset = "1d" | "7d" | "30d" | "90d" | "tm" | "lm";

export const PERIOD_PRESETS: readonly PeriodPreset[] = ["1d", "7d", "30d", "90d", "tm", "lm"];

export const DEFAULT_PRESET: PeriodPreset = "30d";

export interface Period {
  /** Which control is active - `custom` when the range came from the calendar. */
  preset: PeriodPreset | "custom";
  /** Inclusive ISO dates, as GET /stats/usage takes them. */
  from: string;
  to: string;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const RANGE_SEPARATOR = "..";

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function shiftDays(date: Date, days: number): Date {
  const shifted = new Date(date);
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return shifted;
}

/** Turn a preset into its inclusive window. `today` is injectable for tests. */
export function resolvePreset(preset: PeriodPreset, today: Date = new Date()): Period {
  const to = toIsoDate(today);
  switch (preset) {
    case "1d":
      return { preset, from: to, to };
    case "7d":
      return { preset, from: toIsoDate(shiftDays(today, -6)), to };
    case "90d":
      return { preset, from: toIsoDate(shiftDays(today, -89)), to };
    case "tm": {
      const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
      return { preset, from: toIsoDate(first), to };
    }
    case "lm": {
      const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 1, 1));
      const last = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 0));
      return { preset, from: toIsoDate(first), to: toIsoDate(last) };
    }
    default:
      return { preset: "30d", from: toIsoDate(shiftDays(today, -29)), to };
  }
}

/** A calendar-picked range. Either click order works; the dates sort themselves. */
export function customPeriod(a: string, b: string): Period {
  const [from, to] = a <= b ? [a, b] : [b, a];
  return { preset: "custom", from, to };
}

/**
 * Read `?period=` back into a Period. Garbage answers the default rather
 * than an error - a mangled pasted link should still show a dashboard.
 */
export function parsePeriodParam(value: string | null, today: Date = new Date()): Period {
  if (value && (PERIOD_PRESETS as readonly string[]).includes(value)) {
    return resolvePreset(value as PeriodPreset, today);
  }
  if (value?.includes(RANGE_SEPARATOR)) {
    const parts = value.split(RANGE_SEPARATOR);
    const [from, to] = [parts[0] ?? "", parts[1] ?? ""];
    if (ISO_DATE.test(from) && ISO_DATE.test(to)) {
      return customPeriod(from, to);
    }
  }
  return resolvePreset(DEFAULT_PRESET, today);
}

/** The URL form: the preset id, or the range itself for a custom pick. */
export function formatPeriodParam(period: Period): string {
  return period.preset === "custom"
    ? `${period.from}${RANGE_SEPARATOR}${period.to}`
    : period.preset;
}

/**
 * The window as instants, for endpoints that take datetimes rather than dates.
 *
 * A period is inclusive whole days, so the start is the first day's midnight
 * and the end is the last instant of the last day - cutting the end at its
 * midnight would silently drop the day the reader just picked.
 */
export function periodStart(period: Period): string {
  return `${period.from}T00:00:00.000Z`;
}

export function periodEnd(period: Period): string {
  return `${period.to}T23:59:59.999Z`;
}
