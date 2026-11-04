import { describe, expect, it } from "vitest";

import { cadenceBody, cadenceDraftOf, DEFAULT_CADENCE } from "./cadence";

describe("cadence", () => {
  it("turns each form mode into what the Schedule trigger stores", () => {
    expect(cadenceBody(DEFAULT_CADENCE)).toEqual({
      schedule_kind: "interval",
      interval_seconds: 3600,
      cron_expression: null,
    });
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "07:30" })).toEqual({
      schedule_kind: "cron",
      cron_expression: "30 7 * * *",
      interval_seconds: null,
    });
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "cron", cron: " 0  9 * * 1 " })).toEqual({
      schedule_kind: "cron",
      cron_expression: "0 9 * * 1",
      interval_seconds: null,
    });
  });

  it("refuses what could not be scheduled", () => {
    expect(cadenceBody({ ...DEFAULT_CADENCE, count: "0" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, count: "1.5" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "7:30" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "25:00" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "cron", cron: "* * *" })).toBeNull();
  });

  it("reads a node's stored schedule back into the form", () => {
    expect(cadenceDraftOf({ schedule_kind: "interval", interval_seconds: 7200 })).toMatchObject({
      mode: "interval",
      count: "2",
      unit: "hours",
    });
    expect(cadenceDraftOf({})).toMatchObject({ mode: "interval", count: "1", unit: "hours" });
    expect(cadenceDraftOf({ schedule_kind: "cron", cron_expression: "5 8 * * *" })).toMatchObject({
      mode: "daily",
      time: "08:05",
    });
    expect(cadenceDraftOf({ schedule_kind: "cron", cron_expression: "0 9 * * 1-5" })).toMatchObject(
      { mode: "cron", cron: "0 9 * * 1-5" },
    );
  });
});
