import { describe, expect, it } from "vitest";

import { evalSuite, suiteResult, suiteSummary } from "@/test-utils/eval-suites";
import {
  reasonText,
  resultReasons,
  scheduleChoice,
  scheduleCron,
  scheduleText,
  skipText,
  thresholdText,
  whenLabels,
} from "./suite-format";

/** Echoes the key and its values, so a test reads which sentence was chosen. */
const t = (key: string, values?: Record<string, string | number>) =>
  values ? `${key}(${Object.values(values).join(",")})` : key;

describe("schedule choices", () => {
  it("reads a stored schedule back into the form's choices", () => {
    expect(scheduleChoice({ cron: "30 6 * * *", timezone: "UTC" })).toMatchObject({
      frequency: "daily",
      time: "06:30",
    });
    expect(scheduleChoice({ cron: "0 7 * * 1-5", timezone: "UTC" }).frequency).toBe("weekdays");
    expect(scheduleChoice({ cron: "0 7 * * 3", timezone: "UTC" })).toMatchObject({
      frequency: "weekly",
      weekday: 3,
    });
    expect(scheduleChoice({ cron: "0 7 1 * *", timezone: "UTC" }).frequency).toBe("custom");
    expect(scheduleChoice({ cron: "0 7 * * 1,3", timezone: "UTC" }).frequency).toBe("custom");
    expect(scheduleChoice(null)).toMatchObject({ frequency: "daily", time: "06:00" });
  });

  it("compiles the choices back to cron", () => {
    const base = { time: "06:30", weekday: 4, cron: " 0 */2 * * * " };
    expect(scheduleCron({ ...base, frequency: "daily" })).toBe("30 6 * * *");
    expect(scheduleCron({ ...base, frequency: "weekdays" })).toBe("30 6 * * 1-5");
    expect(scheduleCron({ ...base, frequency: "weekly" })).toBe("30 6 * * 4");
    expect(scheduleCron({ ...base, frequency: "custom" })).toBe("0 */2 * * *");
    expect(scheduleCron({ ...base, time: "", frequency: "daily" })).toBe("0 6 * * *");
  });

  it("says a schedule in the zone it is read in", () => {
    const zone = "Europe/Warsaw";
    expect(scheduleText({ cron: "0 6 * * *", timezone: zone }, t, t)).toBe(
      "schedule.daily(06:00,Europe/Warsaw)",
    );
    expect(scheduleText({ cron: "0 6 * * 1-5", timezone: zone }, t, t)).toBe(
      "schedule.weekdays(06:00,Europe/Warsaw)",
    );
    expect(scheduleText({ cron: "0 6 * * 2", timezone: zone }, t, t)).toBe(
      "schedule.weekly(weekdayTue,06:00,Europe/Warsaw)",
    );
    expect(scheduleText({ cron: "0 6 * * 9", timezone: zone }, t, t)).toBe(
      "schedule.custom(0 6 * * 9,Europe/Warsaw)",
    );
  });
});

describe("whenLabels", () => {
  it("lists the schedule first, then each event the suite runs on", () => {
    const suite = evalSuite({ on_promotion: true, on_dependency_change: true });
    expect(whenLabels(suite, t, t)).toEqual([
      "schedule.daily(06:00,Europe/Warsaw)",
      "when.publish",
      "when.promotion",
      "when.dependency",
    ]);
    expect(whenLabels(evalSuite({ schedule: null, on_publish: false }), t, t)).toEqual([]);
  });
});

describe("thresholdText", () => {
  const threshold = {
    min_pass_rate: 0.7,
    max_confirmed_regressions: 2,
    max_cost_per_pass_rise: null,
    max_p95_rise: null,
  };

  it("reads the minimum pass rate in the reader's locale, then the regressions allowed", () => {
    expect(thresholdText(threshold, t, "en")).toBe(
      "threshold.minPassRate(70%) · threshold.regressions(2)",
    );
  });

  it("names only the regressions when there is no minimum pass rate", () => {
    expect(thresholdText({ ...threshold, min_pass_rate: null }, t, "en")).toBe(
      "threshold.regressions(2)",
    );
  });

  it("names the cost and latency rises a result may not exceed, when they are set", () => {
    expect(
      thresholdText({ ...threshold, max_cost_per_pass_rise: 0.2, max_p95_rise: 0.3 }, t, "en"),
    ).toBe(
      "threshold.minPassRate(70%) · threshold.regressions(2) · threshold.costRise(20%) · threshold.p95Rise(30%)",
    );
  });
});

describe("reasonText", () => {
  it("words each way a result falls short, numbers as shares", () => {
    const say = (code: Parameters<typeof reasonText>[0]["code"], value = 0.5, limit = 0.8) =>
      reasonText({ code, value, limit, detail: null }, t, "en");
    expect(say("pass_rate_below")).toBe("reason.passRateBelow(50%,80%)");
    expect(say("nothing_graded")).toBe("reason.nothingGraded");
    expect(say("regressions", 2, 0)).toBe("reason.regressions(2,0)");
    expect(say("cost_per_pass_rise", 0.3, 0.2)).toBe("reason.costRise(30%,20%)");
    expect(say("p95_rise", 1, 0.5)).toBe("reason.p95Rise(100%,50%)");
    expect(say("invalid_comparison")).toBe("reason.invalid");
    expect(say("ungraded", 2)).toBe("reason.ungraded(2)");
    expect(say("incomplete", 1)).toBe("reason.incomplete(1)");
    expect(say("crashed", 3)).toBe("reason.crashed(3)");
    expect(
      reasonText({ code: "regressions", value: null, limit: null, detail: null }, t, "en"),
    ).toBe("reason.regressions(0,0)");
    expect(
      reasonText({ code: "pass_rate_below", value: null, limit: null, detail: null }, t, "en"),
    ).toBe("reason.passRateBelow(0%,0%)");
  });
});

describe("skipText", () => {
  it("words a known reason, and falls back to the message or the code", () => {
    expect(skipText(suiteResult({ status: "skipped", reason: "budget" }), t)).toBe("skip.budget");
    expect(skipText(suiteResult({ status: "error", reason: "start_failed" }), t)).toBe(
      "skip.start_failed",
    );
    expect(skipText(suiteResult({ status: "error", reason: "only_anonymised" }), t)).toBe(
      "skip.only_anonymised",
    );
    expect(
      skipText(
        suiteResult({
          status: "error",
          reason: "something_new",
          summary: suiteSummary({ message: "The worker said why." }),
        }),
        t,
      ),
    ).toBe("The worker said why.");
    expect(skipText(suiteResult({ status: "error", reason: "odd", summary: null }), t)).toBe("odd");
    expect(skipText(suiteResult({ status: "error", reason: null, summary: null }), t)).toBeNull();
  });
});

describe("resultReasons", () => {
  const shortfall = {
    code: "pass_rate_below" as const,
    value: 0.5,
    limit: 0.8,
    detail: null,
  };

  it("gives a verdict the threshold's reasons", () => {
    const failed = suiteResult({
      status: "failed",
      summary: suiteSummary({ reasons: [shortfall] }),
    });
    expect(resultReasons(failed, t, "en")).toEqual(["reason.passRateBelow(50%,80%)"]);
  });

  it("gives an inconclusive result with no threshold to fall short of its own reason", () => {
    const cancelled = suiteResult({ status: "inconclusive", reason: "cancelled", summary: null });
    expect(resultReasons(cancelled, t, "en")).toEqual(["skip.cancelled"]);
    expect(
      resultReasons(suiteResult({ status: "inconclusive", reason: null, summary: null }), t, "en"),
    ).toEqual([]);
  });

  it("words a result that did not run, and says nothing of a pass or a failure without reasons", () => {
    expect(resultReasons(suiteResult({ status: "skipped", reason: "budget" }), t, "en")).toEqual([
      "skip.budget",
    ]);
    expect(resultReasons(suiteResult({ status: "passed" }), t, "en")).toEqual([]);
    expect(
      resultReasons(suiteResult({ status: "failed", reason: "cancelled", summary: null }), t, "en"),
    ).toEqual([]);
  });

  it("says first that a result was not compared when a pair would have crossed the ceiling", () => {
    const alone = (status: "passed" | "failed") =>
      suiteResult({
        status,
        reason: "not_compared_cost_cap",
        summary: suiteSummary({ reasons: status === "failed" ? [shortfall] : [] }),
      });
    expect(resultReasons(alone("passed"), t, "en")).toEqual(["notCompared"]);
    expect(resultReasons(alone("failed"), t, "en")).toEqual([
      "notCompared",
      "reason.passRateBelow(50%,80%)",
    ]);
  });
});
