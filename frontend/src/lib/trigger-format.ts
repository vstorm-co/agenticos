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
 * fires on its default action and the generic webhook on any signed delivery, so
 * neither offers a filter; email narrows by subject and sender, LinkedIn by
 * author and post text.
 */
export const FILTER_KEYS: Partial<Record<EventSource, readonly [string, string]>> = {
  email: ["subject_contains", "sender_contains"],
  linkedin: ["author_contains", "text_contains"],
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
    // portal and its target are both known. The target comes from the backend's
    // `provider_target`, so until `TriggerRead` exposes it a preset trigger falls
    // back to the generic per-source label rather than showing half a sentence.
    if (trigger.portal_key && trigger.provider_target) {
      return { kind: "preset", portalKey: trigger.portal_key, target: trigger.provider_target };
    }
    return { kind: "event", source: trigger.event_source ?? "github" };
  }
  if (trigger.schedule_kind === "cron") {
    return { kind: "cron", expression: trigger.cron_expression ?? "" };
  }
  const { unit, count } = intervalToUnit(trigger.interval_seconds ?? MINUTE);
  return { kind: "interval", unit, count };
}
