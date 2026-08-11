import { describe, expect, it } from "vitest";

import { intervalToUnit, triggerSummary, unitToSeconds } from "./trigger-format";
import type { Trigger } from "@/types/triggers";

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: null,
    created_by_user_id: null,
    is_active: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 300,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "run",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_path: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("intervalToUnit", () => {
  it("reduces to the largest whole unit", () => {
    // 3600s is an hour, not sixty minutes - the label should say so.
    expect(intervalToUnit(86400)).toEqual({ unit: "days", count: 1 });
    expect(intervalToUnit(7200)).toEqual({ unit: "hours", count: 2 });
    expect(intervalToUnit(900)).toEqual({ unit: "minutes", count: 15 });
  });

  it("rounds a non-multiple to the nearest minute rather than showing seconds", () => {
    expect(intervalToUnit(90)).toEqual({ unit: "minutes", count: 2 });
    // Never zero: a sub-minute value still reads as one minute.
    expect(intervalToUnit(20)).toEqual({ unit: "minutes", count: 1 });
  });
});

describe("unitToSeconds", () => {
  it("is the inverse the builder writes back", () => {
    expect(unitToSeconds("days", 1)).toBe(86400);
    expect(unitToSeconds("hours", 2)).toBe(7200);
    expect(unitToSeconds("minutes", 15)).toBe(900);
  });
});

describe("triggerSummary", () => {
  it("describes an interval schedule by its largest unit", () => {
    expect(triggerSummary(trigger({ interval_seconds: 3600 }))).toEqual({
      kind: "interval",
      unit: "hours",
      count: 1,
    });
  });

  it("carries a cron expression through verbatim", () => {
    expect(
      triggerSummary(
        trigger({ schedule_kind: "cron", interval_seconds: null, cron_expression: "0 9 * * *" }),
      ),
    ).toEqual({ kind: "cron", expression: "0 9 * * *" });
  });

  it("names an event trigger by its source", () => {
    expect(
      triggerSummary(
        trigger({ trigger_type: "event", schedule_kind: "interval", event_source: "email" }),
      ),
    ).toEqual({ kind: "event", source: "email" });
  });

  it("falls back to a sensible default when a discriminant's own field is null", () => {
    // The shape CHECK makes these unreachable in practice, but the type allows a
    // null, so the summary picks a default rather than rendering "undefined".
    expect(triggerSummary(trigger({ trigger_type: "event", event_source: null }))).toEqual({
      kind: "event",
      source: "github",
    });
    expect(
      triggerSummary(
        trigger({ schedule_kind: "cron", cron_expression: null, interval_seconds: null }),
      ),
    ).toEqual({ kind: "cron", expression: "" });
    expect(triggerSummary(trigger({ interval_seconds: null }))).toEqual({
      kind: "interval",
      unit: "minutes",
      count: 1,
    });
  });
});
