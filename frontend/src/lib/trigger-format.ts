import type { EventSource, Trigger } from "@/types/triggers";

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export type IntervalUnit = "minutes" | "hours" | "days";

/**
 * A trigger's cadence reduced to what a *static* translated label needs.
 *
 * A discriminated union rather than a formatted string, so the component switches
 * on `kind` and calls the translator with fixed keys - a formatted English string
 * here could not be translated, and a dynamic `t(key)` could not be verified by
 * the i18n catalog check.
 */
export type TriggerSummary =
  | { kind: "interval"; unit: IntervalUnit; count: number }
  | { kind: "cron"; expression: string }
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

/** What makes this trigger fire, reduced for display. */
export function triggerSummary(trigger: Trigger): TriggerSummary {
  if (trigger.trigger_type === "event") {
    return { kind: "event", source: trigger.event_source ?? "github" };
  }
  if (trigger.schedule_kind === "cron") {
    return { kind: "cron", expression: trigger.cron_expression ?? "" };
  }
  const { unit, count } = intervalToUnit(trigger.interval_seconds ?? MINUTE);
  return { kind: "interval", unit, count };
}
