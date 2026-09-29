import { type IntervalUnit, intervalToUnit, parseCron, unitToSeconds } from "@/lib/trigger-format";
import type { WorkflowExposureRead, WorkflowExposureUpdate } from "@/lib/workflows/types";

/**
 * The three ways the schedule form sets a cadence: every so often, daily at a
 * time, or a crontab for anything else. All evaluated in UTC by the server.
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

/** A new schedule opens on "every hour" - often enough to see it work. */
export const DEFAULT_CADENCE: CadenceDraft = {
  mode: "interval",
  count: "1",
  unit: "hours",
  time: "09:00",
  cron: "0 9 * * 1-5",
};

/** The form's cadence, seeded from a schedule that already exists. */
export function cadenceDraftOf(exposure: WorkflowExposureRead): CadenceDraft {
  if (exposure.schedule_kind === "cron" && exposure.cron_expression) {
    const parsed = parseCron(exposure.cron_expression);
    if (parsed.freq === "daily") return { ...DEFAULT_CADENCE, mode: "daily", time: parsed.time };
    return { ...DEFAULT_CADENCE, mode: "cron", cron: exposure.cron_expression };
  }
  const { unit, count } = intervalToUnit(exposure.interval_seconds ?? 3600);
  return { ...DEFAULT_CADENCE, mode: "interval", unit, count: String(count) };
}

/**
 * What the draft sends, or null while it cannot be scheduled - a count under
 * a minute, a time that is not `HH:MM`, a crontab that is not five fields.
 * The server re-validates the crontab; this only keeps an obviously
 * unschedulable form from being submitted.
 */
export function cadenceBody(
  draft: CadenceDraft,
): Pick<WorkflowExposureUpdate, "schedule_kind" | "interval_seconds" | "cron_expression"> | null {
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
