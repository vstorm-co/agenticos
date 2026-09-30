import { type IntervalUnit, intervalToUnit, parseCron, unitToSeconds } from "@/lib/trigger-format";

/**
 * The three ways the Schedule trigger's form sets a cadence: every so often,
 * daily at a time, or a crontab for anything else. All evaluated in UTC by the
 * server.
 */
export type CadenceMode = "interval" | "daily" | "cron";

export interface CadenceDraft {
  mode: CadenceMode;
  count: string;
  unit: IntervalUnit;
  /** `HH:MM`, for `daily`. */
  time: string;
  cron: string;
}

/** The cadence fields of `ScheduleTriggerConfig`, as the node's config stores them. */
export interface CadenceConfig {
  schedule_kind: "interval" | "cron";
  interval_seconds: number | null;
  cron_expression: string | null;
}

/** A new schedule opens on "every hour" - the node's own default. */
export const DEFAULT_CADENCE: CadenceDraft = {
  mode: "interval",
  count: "1",
  unit: "hours",
  time: "09:00",
  cron: "0 9 * * 1-5",
};

/** The form's cadence, seeded from what the node's config holds. */
export function cadenceDraftOf(config: Partial<CadenceConfig>): CadenceDraft {
  if (config.schedule_kind === "cron" && config.cron_expression) {
    const parsed = parseCron(config.cron_expression);
    if (parsed.freq === "daily") return { ...DEFAULT_CADENCE, mode: "daily", time: parsed.time };
    return { ...DEFAULT_CADENCE, mode: "cron", cron: config.cron_expression };
  }
  const { unit, count } = intervalToUnit(config.interval_seconds ?? 3600);
  return { ...DEFAULT_CADENCE, mode: "interval", unit, count: String(count) };
}

/**
 * What the draft writes into the node's config, or null while it cannot be
 * scheduled - a count under a minute, a time that is not `HH:MM`, a crontab
 * that is not five fields. Publishing re-validates the crontab; this only keeps
 * an obviously unschedulable cadence out of the graph.
 */
export function cadenceBody(draft: CadenceDraft): CadenceConfig | null {
  if (draft.mode === "interval") {
    const count = Number(draft.count);
    // A whole number of minutes at least - the server's floor, since its heartbeat
    // ticks once a minute and the smallest unit here is a minute.
    if (!Number.isInteger(count) || count < 1) return null;
    return {
      schedule_kind: "interval",
      interval_seconds: unitToSeconds(draft.unit, count),
      cron_expression: null,
    };
  }
  if (draft.mode === "daily") {
    const match = /^(\d{2}):(\d{2})$/.exec(draft.time);
    if (!match) return null;
    const [hour, minute] = [Number(match[1]), Number(match[2])];
    if (hour > 23 || minute > 59) return null;
    return {
      schedule_kind: "cron",
      cron_expression: `${minute} ${hour} * * *`,
      interval_seconds: null,
    };
  }
  const expression = draft.cron.trim().replace(/\s+/g, " ");
  if (expression.split(" ").length !== 5) return null;
  return { schedule_kind: "cron", cron_expression: expression, interval_seconds: null };
}
