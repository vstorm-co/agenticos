import { describe, expect, it } from "vitest";

import {
  cadenceText,
  intervalToUnit,
  parseCron,
  triggerSummary,
  unitToSeconds,
  weekdayKey,
} from "./trigger-format";
import type { Trigger } from "@/types/triggers";

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: null,
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
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
    webhook_url: null,
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

describe("parseCron", () => {
  const advanced = (expression: string) => expect(parseCron(expression).freq).toBe("advanced");

  it("recognises exactly the shapes the builder writes", () => {
    expect(parseCron("0 9 * * *")).toMatchObject({ freq: "daily", time: "09:00" });
    expect(parseCron("5 7 */3 * *")).toMatchObject({
      freq: "everyNDays",
      time: "07:05",
      everyDays: "3",
    });
    expect(parseCron("0 9 * * 1,3,5")).toMatchObject({ freq: "weekly", weekdays: [1, 3, 5] });
    expect(parseCron("0 9 31 * *")).toMatchObject({ freq: "monthly", dayOfMonth: "31" });
  });

  it("falls back to advanced for anything else", () => {
    advanced(""); // not five fields
    advanced("0 9 * *"); // four fields
    advanced("*/5 * * * *"); // no fixed minute
    advanced("0 24 * * *"); // hour out of range
    advanced("0 9 * 6 *"); // a fixed month is not a builder shape
    advanced("0 9 * * 9"); // weekday out of range
    advanced("0 9 * * 1-5"); // a range is not the builder's comma list
    advanced("0 9 15 * 1"); // day-of-month and weekday together
    advanced("0 9 0 * *"); // day-of-month out of range
    advanced("0 9 */2 * 1"); // every-N-days combined with a weekday
  });
});

describe("weekdayKey", () => {
  it("names a weekday and defaults to Monday off-range", () => {
    expect(weekdayKey(0)).toBe("weekdaySun");
    expect(weekdayKey(7)).toBe("weekdayMon");
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

  it("reads a builder-shaped cron in plain language, not notation", () => {
    const cron = (expression: string) =>
      triggerSummary(
        trigger({ schedule_kind: "cron", interval_seconds: null, cron_expression: expression }),
      );
    expect(cron("0 9 * * *")).toEqual({ kind: "cronDaily", time: "09:00" });
    expect(cron("30 18 * * 1,2")).toEqual({ kind: "cronWeekly", time: "18:30", weekdays: [1, 2] });
    expect(cron("0 9 15 * *")).toEqual({ kind: "cronMonthly", time: "09:00", day: 15 });
    // Every N days reads exactly like an interval in days - same label, same key.
    expect(cron("0 9 */2 * *")).toEqual({ kind: "interval", unit: "days", count: 2 });
  });

  it("carries a hand-written cron expression through verbatim", () => {
    // Only an expression the builder could not have produced keeps its raw
    // notation - that user chose Advanced and wants to see what they wrote.
    expect(
      triggerSummary(
        trigger({ schedule_kind: "cron", interval_seconds: null, cron_expression: "*/5 * * * *" }),
      ),
    ).toEqual({ kind: "cron", expression: "*/5 * * * *" });
  });

  it("reads a portal preset as its portal and target when both are known", () => {
    expect(
      triggerSummary(
        trigger({
          trigger_type: "event",
          event_source: "github",
          portal_key: "github",
          provider_target: "acme/repo",
        }),
      ),
    ).toEqual({ kind: "preset", portalKey: "github", target: "acme/repo" });
  });

  it("falls back to the generic event label when a preset has no target yet", () => {
    // `TriggerRead` does not expose the target today, so a preset with only its
    // portal key reads as the plain source rather than half a sentence.
    expect(
      triggerSummary(
        trigger({ trigger_type: "event", event_source: "github", portal_key: "github" }),
      ),
    ).toEqual({ kind: "event", source: "github" });
  });

  it("names an event trigger by its source", () => {
    expect(
      triggerSummary(
        trigger({ trigger_type: "event", schedule_kind: "interval", event_source: "gmail" }),
      ),
    ).toEqual({ kind: "event", source: "gmail" });
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

describe("cadenceText", () => {
  // The sentence two surfaces read - `TriggerSummary` renders it, the dashboard's
  // routines card puts it beside a cost - so it is asserted here rather than
  // through either of them. `t` echoes the key and its values, which is what makes
  // the branch visible: the point of each case is *which* message and *which*
  // parameters, not the English.
  const t = (key: string, values?: Record<string, string | number>) =>
    values === undefined ? key : `${key}(${JSON.stringify(values)})`;

  it("reads an interval through its own unit's plural", () => {
    expect(cadenceText(trigger({ interval_seconds: 900 }), t)).toBe(
      'cadence.everyMinutes({"count":15})',
    );
    expect(cadenceText(trigger({ interval_seconds: 7200 }), t)).toBe(
      'cadence.everyHours({"count":2})',
    );
    expect(cadenceText(trigger({ interval_seconds: 172800 }), t)).toBe(
      'cadence.everyDays({"count":2})',
    );
  });

  it("reads a builder-made cron in the language the builder showed", () => {
    const cron = (expression: string) =>
      cadenceText(trigger({ schedule_kind: "cron", cron_expression: expression }), t);

    expect(cron("0 9 * * *")).toBe('cadence.cronDaily({"time":"09:00"})');
    // The weekday names are themselves keys, resolved by the same translator -
    // Monday-first, the order the picker shows, not cron's Sunday-zero order.
    expect(cron("0 9 * * 1,2")).toBe(
      'cadence.cronWeekly({"time":"09:00","days":"weekdayMon, weekdayTue"})',
    );
    expect(cron("0 9 3 * *")).toBe('cadence.cronMonthly({"day":3,"time":"09:00"})');
    expect(cron("0 9 */3 * *")).toBe('cadence.everyDays({"count":3})');
  });

  it("shows raw notation only for an expression somebody typed themselves", () => {
    expect(cadenceText(trigger({ schedule_kind: "cron", cron_expression: "*/7 * * * *" }), t)).toBe(
      'cadence.cron({"expression":"*/7 * * * *"})',
    );
  });

  it("names each event source", () => {
    const event = (source: "github" | "gmail" | "webhook") =>
      cadenceText(trigger({ trigger_type: "event", event_source: source }), t);

    expect(event("github")).toBe("event.github");
    expect(event("gmail")).toBe("event.gmail");
    expect(event("webhook")).toBe("event.webhook");
  });

  it("reads a preset as one sentence, with the portal's own phrase in it", () => {
    // A preset that knows its target reads "New issue in acme/repo" - one ICU
    // message with the event phrase interpolated, never two halves glued in the
    // component.
    const preset = (portal: string) =>
      cadenceText(
        trigger({
          trigger_type: "event",
          event_source: "github",
          portal_key: portal,
          provider_target: "acme/repo",
        }),
        t,
      );

    expect(preset("github")).toBe(
      'event.presetSummary({"event":"event.presetGithub","target":"acme/repo"})',
    );
    expect(preset("google")).toBe(
      'event.presetSummary({"event":"event.presetGmail","target":"acme/repo"})',
    );
    // A portal added to the catalog tomorrow has no phrase of its own and takes
    // the generic one, rather than rendering a missing key.
    expect(preset("linear")).toBe(
      'event.presetSummary({"event":"event.presetGeneric","target":"acme/repo"})',
    );
  });
});
