import { describe, expect, it } from "vitest";
import { contextSettings } from "./context-settings";

describe("per-agent context settings", () => {
  it("keeps old bindings without overrides", () => {
    for (const value of [undefined, null, [], {}, 1, "invalid"])
      expect(contextSettings(value)).toEqual({});
  });
  it("reads disabled and linked overrides and applies schema defaults", () => {
    expect(contextSettings({ one: { mode: "link", enabled: false }, two: {} })).toEqual({
      one: { mode: "link", enabled: false },
      two: { mode: "inject", enabled: true },
    });
  });
  it("does not promote malformed policy into a valid override", () => {
    expect(
      contextSettings({
        bad: [],
        mode: { mode: "unknown" },
        enabled: { enabled: "false" },
        null: null,
      }),
    ).toEqual({});
  });
});

it("keeps external dictionary keys as data rather than altering its prototype", () => {
  const raw: unknown = JSON.parse('{"__proto__":{"mode":"link","enabled":false}}');
  const result = contextSettings(raw);
  expect(Object.hasOwn(result, "__proto__")).toBe(true);
  expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
});
