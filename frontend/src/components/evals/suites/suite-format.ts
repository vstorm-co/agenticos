import type { Translate } from "@/lib/agent-step-captions";
import { parseCron, weekdayKey } from "@/lib/trigger-format";
import type {
  EvalSuite,
  EvalSuiteResult,
  EvalSuiteResultStatus,
  EvalSuiteSchedule,
  EvalSuiteThreshold,
  ThresholdReason,
} from "@/types/eval-suites";
import { percent } from "../format";

/** The colour of a result, in the verdict's own: red breaks, green passes, amber says nothing. */
export const RESULT_TONE: Record<
  EvalSuiteResultStatus,
  "secondary" | "success" | "warning" | "destructive" | "outline"
> = {
  pending: "outline",
  running: "secondary",
  passed: "success",
  failed: "destructive",
  inconclusive: "warning",
  skipped: "warning",
  error: "warning",
};

export type SuiteState = "failing" | "passing" | "waiting" | "paused";

/**
 * Where a suite stands, by its last result - a paused one is paused whatever it
 * last did, and a result the server marks `alerting`, anything but a pass, is
 * failing: the same rule its owner is notified by.
 */
export function suiteState(suite: EvalSuite): SuiteState {
  if (!suite.is_active) return "paused";
  if (suite.last_result?.alerting) return "failing";
  if (suite.last_result?.status === "passed") return "passing";
  return "waiting";
}

/** The repeat choices the form offers; `custom` takes a cron expression as it is. */
export type ScheduleFrequency = "daily" | "weekdays" | "weekly" | "custom";

export interface ScheduleChoice {
  frequency: ScheduleFrequency;
  /** `HH:MM` on the zone's wall clock. */
  time: string;
  /** Cron's numbering, 0 = Sunday. */
  weekday: number;
  cron: string;
}

/** A stored schedule read back into the form's choices; one no preset says is `custom`. */
export function scheduleChoice(schedule: EvalSuiteSchedule | null): ScheduleChoice {
  const cron = schedule?.cron ?? "0 6 * * *";
  const parsed = parseCron(cron);
  const choice = { time: parsed.time, weekday: Math.min(...parsed.weekdays), cron };
  if (parsed.freq === "daily") return { ...choice, frequency: "daily" };
  if (parsed.freq === "weekly" && [...parsed.weekdays].sort().join(",") === "1,2,3,4,5") {
    return { ...choice, frequency: "weekdays" };
  }
  if (parsed.freq === "weekly" && parsed.weekdays.length === 1) {
    return { ...choice, frequency: "weekly" };
  }
  return { ...choice, frequency: "custom" };
}

/** The cron expression the form's choices compile to. */
export function scheduleCron(choice: ScheduleChoice): string {
  if (choice.frequency === "custom") return choice.cron.trim();
  const [, hour = "6", minute = "0"] = /^(\d{1,2}):(\d{2})/.exec(choice.time) ?? [];
  const at = `${Number(minute)} ${Number(hour)}`;
  if (choice.frequency === "daily") return `${at} * * *`;
  if (choice.frequency === "weekdays") return `${at} * * 1-5`;
  return `${at} * * ${choice.weekday}`;
}

/**
 * A schedule in one line - "Daily at 06:00 (Europe/Warsaw)". Takes the suites'
 * translator for the sentence and the triggers' for a weekday's name, which is
 * where the console keeps them.
 */
export function scheduleText(schedule: EvalSuiteSchedule, t: Translate, days: Translate): string {
  const choice = scheduleChoice(schedule);
  const zone = schedule.timezone;
  switch (choice.frequency) {
    case "daily":
      return t("schedule.daily", { time: choice.time, zone });
    case "weekdays":
      return t("schedule.weekdays", { time: choice.time, zone });
    case "weekly":
      return t("schedule.weekly", {
        day: days(weekdayKey(choice.weekday)),
        time: choice.time,
        zone,
      });
    case "custom":
      return t("schedule.custom", { expression: schedule.cron, zone });
  }
}

/** When a suite runs, as the labels its row shows - the schedule first. */
export function whenLabels(suite: EvalSuite, t: Translate, days: Translate): string[] {
  const labels: string[] = [];
  if (suite.schedule) labels.push(scheduleText(suite.schedule, t, days));
  if (suite.on_publish) labels.push(t("when.publish"));
  if (suite.on_promotion) labels.push(t("when.promotion"));
  if (suite.on_dependency_change) labels.push(t("when.dependency"));
  return labels;
}

/** What a result must meet, as its row shows it - "≥70% · 0 regressions · cost/pass ≤+20%". */
export function thresholdText(threshold: EvalSuiteThreshold, t: Translate, locale: string): string {
  const parts: string[] = [];
  if (threshold.min_pass_rate !== null) {
    parts.push(t("threshold.minPassRate", { rate: percent(threshold.min_pass_rate, locale) }));
  }
  parts.push(t("threshold.regressions", { count: threshold.max_confirmed_regressions }));
  if (threshold.max_cost_per_pass_rise !== null) {
    parts.push(
      t("threshold.costRise", { rise: percent(threshold.max_cost_per_pass_rise, locale) }),
    );
  }
  if (threshold.max_p95_rise !== null) {
    parts.push(t("threshold.p95Rise", { rise: percent(threshold.max_p95_rise, locale) }));
  }
  return parts.join(" · ");
}

/** One way a result fell short, in words, with its numbers in the reader's locale. */
export function reasonText(reason: ThresholdReason, t: Translate, locale: string): string {
  const share = (value: number | null) =>
    new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(
      value ?? 0,
    );
  switch (reason.code) {
    case "pass_rate_below":
      return t("reason.passRateBelow", { value: share(reason.value), limit: share(reason.limit) });
    case "nothing_graded":
      return t("reason.nothingGraded");
    case "regressions":
      return t("reason.regressions", { count: reason.value ?? 0, limit: reason.limit ?? 0 });
    case "cost_per_pass_rise":
      return t("reason.costRise", { value: share(reason.value), limit: share(reason.limit) });
    case "p95_rise":
      return t("reason.p95Rise", { value: share(reason.value), limit: share(reason.limit) });
    case "invalid_comparison":
      return t("reason.invalid");
    case "ungraded":
      return t("reason.ungraded", { count: reason.value ?? 0 });
    case "incomplete":
      return t("reason.incomplete", { count: reason.value ?? 0 });
    case "crashed":
      return t("reason.crashed", { count: reason.value ?? 0 });
  }
}

/** The codes a result that did not run is worded by; anything else reads as its message. */
const KNOWN_SKIPS = new Set([
  "budget",
  "over_cost_cap",
  "ai_assistance_off",
  "no_scorer",
  "only_anonymised",
  "not_published",
  "version_gone",
  "owner_inactive",
  "owner_lacks_access",
  "not_runnable",
  "run_gone",
  "cancelled",
  "failed",
  "budget_exceeded",
  "start_failed",
  "settle_failed",
]);

/** Why a result skipped or ended without a verdict, in the console's words where it has them. */
export function skipText(result: EvalSuiteResult, t: Translate): string | null {
  if (result.reason !== null && KNOWN_SKIPS.has(result.reason)) {
    return t(`skip.${result.reason}`);
  }
  return result.summary?.message ?? result.reason;
}

/**
 * Why a result came out as it did, a line each: the threshold's reasons for a
 * failure or an inconclusive verdict, and the result's own reason where it has
 * no threshold to fall short of - a run that was cancelled, one that never ran.
 */
export function resultReasons(result: EvalSuiteResult, t: Translate, locale: string): string[] {
  const reasons = result.summary?.reasons ?? [];
  if ((result.status === "failed" || result.status === "inconclusive") && reasons.length > 0) {
    return reasons.map((reason) => reasonText(reason, t, locale));
  }
  if (["inconclusive", "skipped", "error"].includes(result.status)) {
    return [skipText(result, t)].filter((text): text is string => text !== null);
  }
  return [];
}
