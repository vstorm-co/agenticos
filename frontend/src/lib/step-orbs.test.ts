import { describe, expect, it } from "vitest";

import { STEP_ICONS } from "./step-icons";
import { STEP_ORBS } from "./step-orbs";

/**
 * The orb a running step wears. The table is only useful if it answers for every
 * kind the step list can draw, which is the one thing worth asserting about it.
 */
describe("STEP_ORBS", () => {
  it("answers for every kind the icons answer for", () => {
    // Both tables are keyed by `StepKind`. A kind added to one and not the other
    // is the drift the file's own comment is about.
    expect(Object.keys(STEP_ORBS).sort()).toEqual(Object.keys(STEP_ICONS).sort());
  });

  it("leaves listening to the microphone", () => {
    // `listening` is a person being heard, which no tool call is.
    expect(Object.values(STEP_ORBS)).not.toContain("listening");
  });
});
