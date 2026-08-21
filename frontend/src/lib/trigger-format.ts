import type { EventSource, Trigger } from "@/types/triggers";

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export type IntervalUnit = "minutes" | "hours" | "days";

/**
 * The builder's repeat choices. Everything but `advanced` maps to a crontab
 * shape: daily `M H * * *`, every-N-days `M H * / N * *`, weekly `M H * * <days>`,
 * monthly `M H <dom> * *`. `advanced` is the escape hatch that takes a raw
 * expression for the cases the presets do not cover.
 */
export type CronFrequency = "daily" | "everyNDays" | "weekly" | "monthly" | "advanced";

/** The weekdays, in cron's numbering (0 = Sunday), Monday-first for display. */
export const WEEKDAYS: readonly { value: number; key: string }[] = [
  { value: 1, key: "weekdayMon" },
  { value: 2, key: "weekdayTue" },
  { value: 3, key: "weekdayWed" },
  { value: 4, key: "weekdayThu" },
  { value: 5, key: "weekdayFri" },
  { value: 6, key: "weekdaySat" },
  { value: 0, key: "weekdaySun" },
];

/** The translation key for a weekday value, defaulting to Monday off-range. */
export function weekdayKey(value: number): string {
  return WEEKDAYS.find((day) => day.value === value)?.key ?? "weekdayMon";
}

/** The builder state a cron expression seeds, for editing an existing schedule. */
export interface ParsedCron {
  freq: CronFrequency;
  time: string;
  everyDays: string;
  weekdays: number[];
  dayOfMonth: string;
}

/**
 * A cron expression read back into the builder's choices, or "advanced" when no
 * preset represents it. Only the shapes the builder produces are recognised - a
 * fixed minute and hour, a wildcard month, and one of daily / every-N-days /
 * weekdays / day-of-month - so a builder-made schedule round-trips on edit and
 * reads back in plain language, and a hand-written one stays on its raw
 * expression rather than a wrong preset.
 */
export function parseCron(expression: string): ParsedCron {
  const fallback: ParsedCron = {
    freq: "advanced",
    time: "09:00",
    everyDays: "2",
    weekdays: [1],
    dayOfMonth: "1",
  };
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return fallback;
  const [rawMinute, rawHour, dom, month, dow] = parts as [string, string, string, string, string];
  const minute = Number(rawMinute);
  const hour = Number(rawHour);
  const timed =
    Number.isInteger(minute) &&
    minute >= 0 &&
    minute <= 59 &&
    Number.isInteger(hour) &&
    hour >= 0 &&
    hour <= 23;
  if (!timed || month !== "*") return fallback;
  const time = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  if (dom === "*" && dow === "*") return { ...fallback, freq: "daily", time };
  const everyN = /^\*\/([0-9]+)$/.exec(dom)?.[1];
  if (everyN !== undefined && dow === "*") {
    return { ...fallback, freq: "everyNDays", time, everyDays: everyN };
  }
  if (dom === "*" && dow !== "*") {
    const days = dow.split(",").map(Number);
    if (days.every((day) => Number.isInteger(day) && day >= 0 && day <= 6)) {
      return { ...fallback, freq: "weekly", time, weekdays: days };
    }
    return fallback;
  }
  const day = Number(dom);
  if (dow === "*" && Number.isInteger(day) && day >= 1 && day <= 31) {
    return { ...fallback, freq: "monthly", time, dayOfMonth: String(day) };
  }
  return fallback;
}

/**
 * A trigger's cadence reduced to what a *static* translated label needs.
 *
 * A discriminated union rather than a formatted string, so the component switches
 * on `kind` and calls the translator with fixed keys - a formatted English string
 * here could not be translated, and a dynamic `t(key)` could not be verified by
 * the i18n catalog check.
 *
 * A cron expression the builder could have written comes back as its plain shape
 * (`cronDaily`, `cronWeekly`, `cronMonthly`, or the same `interval` days read an
 * interval gets); the raw `cron` kind is only for an expression the user wrote
 * themselves in Advanced, which is the one audience that wants the notation.
 */
export type TriggerSummary =
  | { kind: "interval"; unit: IntervalUnit; count: number }
  | { kind: "cron"; expression: string }
  | { kind: "cronDaily"; time: string }
  | { kind: "cronWeekly"; time: string; weekdays: number[] }
  | { kind: "cronMonthly"; time: string; day: number }
  | { kind: "preset"; portalKey: string; target: string }
  | { kind: "event"; source: EventSource };

/**
 * The largest whole unit an interval divides into, so 3600s reads "every hour"
 * rather than "every 60 minutes". The cadence builder only ever writes clean
 * multiples; the fall-through to minutes is for a value typed straight into the
 * API, which is rounded to the nearest minute rather than shown to the second.
 */
export function intervalToUnit(seconds: number): { unit: IntervalUnit; count: number } {
  if (seconds % DAY === 0) return { unit: "days", count: seconds / DAY };
  if (seconds % HOUR === 0) return { unit: "hours", count: seconds / HOUR };
  return { unit: "minutes", count: Math.max(1, Math.round(seconds / MINUTE)) };
}

/** The seconds a unit-and-count means, for the cadence builder writing a value. */
export function unitToSeconds(unit: IntervalUnit, count: number): number {
  const factor = unit === "days" ? DAY : unit === "hours" ? HOUR : MINUTE;
  return count * factor;
}

/**
 * The two `event_config` keys each source's optional substring filters map onto,
 * or none. Shared by both trigger builders - the raw source-and-secret form and
 * the friendly portal dialog - so a source is described in one place: GitHub
 * fires on its default action and the API source on any signed delivery, so
 * neither offers a filter; Gmail narrows by subject and sender.
 */
export const FILTER_KEYS: Partial<Record<EventSource, readonly [string, string]>> = {
  gmail: ["subject_contains", "sender_contains"],
};

/**
 * The `event_config` a source's substring filters produce, or undefined when the
 * source takes none. `values` are the field inputs in the order `FILTER_KEYS`
 * lists them; each is trimmed and only a non-empty one is sent, so the server
 * stores exactly what narrows the trigger and nothing that means "match anything".
 */
export function eventFilterConfig(
  source: EventSource,
  values: readonly string[],
): Record<string, string> | undefined {
  const keys = FILTER_KEYS[source];
  if (!keys) return undefined;
  const config: Record<string, string> = {};
  keys.forEach((key, index) => {
    const value = values[index]?.trim();
    if (value) config[key] = value;
  });
  return Object.keys(config).length ? config : undefined;
}

/** What makes this trigger fire, reduced for display. */
export function triggerSummary(trigger: Trigger): TriggerSummary {
  if (trigger.trigger_type === "event") {
    // A preset reads in plain language - "New issue in acme/repo" - when the
    // portal and its target (the backend's `provider_target`) are both known; a
    // source with no target - a schedule, a manual trigger, an auto one with none
    // chosen - falls back to the generic per-source label rather than half a
    // sentence.
    if (trigger.portal_key && trigger.provider_target) {
      return { kind: "preset", portalKey: trigger.portal_key, target: trigger.provider_target };
    }
    return { kind: "event", source: trigger.event_source ?? "github" };
  }
  if (trigger.schedule_kind === "cron") {
    const expression = trigger.cron_expression ?? "";
    const parsed = parseCron(expression);
    switch (parsed.freq) {
      case "daily":
        return { kind: "cronDaily", time: parsed.time };
      case "everyNDays":
        return { kind: "interval", unit: "days", count: Math.max(1, Number(parsed.everyDays)) };
      case "weekly":
        return { kind: "cronWeekly", time: parsed.time, weekdays: parsed.weekdays };
      case "monthly":
        return { kind: "cronMonthly", time: parsed.time, day: Number(parsed.dayOfMonth) };
      case "advanced":
        return { kind: "cron", expression };
    }
  }
  const { unit, count } = intervalToUnit(trigger.interval_seconds ?? MINUTE);
  return { kind: "interval", unit, count };
}
