import { describe, expect, it } from "vitest";

import { endInput, endInstant } from "./ends-at-field";

describe("routine end time", () => {
  it("keeps no end distinct from invalid input", () => {
    expect(endInput(null)).toBe("");
    expect(endInstant("")).toBeNull();
    expect(endInstant("invalid")).toBeUndefined();
    expect(endInstant("2027-02-31T12:00")).toBeUndefined();
  });

  it("sends an offset-aware instant for the local device time", () => {
    const local = "2099-01-01T12:00";
    const instant = endInstant(local);
    expect(instant).toMatch(/Z$/);
    expect(instant && endInput(instant)).toBe(local);
  });
});
