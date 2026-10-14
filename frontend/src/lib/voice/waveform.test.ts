import { describe, expect, it } from "vitest";

import { agentShare, barTarget, easeBar, waveVisual, type WaveVisual } from "./waveform";

const SILENT = { input: 0, output: 0 };
const LOUD = { input: 1, output: 1 };

describe("waveVisual", () => {
  it.each([
    ["connecting", "connecting"],
    ["reconnecting", "connecting"],
    ["listening", "listening"],
    ["limitwarn", "listening"],
    ["user", "user"],
    ["agent", "agent"],
    ["interrupted", "interrupted"],
    ["thinking", "thinking"],
    ["tool", "tool"],
    ["approval", "approval"],
    ["noapproval", "quiet"],
    ["ended", "quiet"],
  ] as const)("draws %s as %s", (view, visual) => {
    expect(waveVisual(view, true)).toBe(visual);
  });

  it("draws a closed microphone as quiet while the call listens", () => {
    expect(waveVisual("listening", false)).toBe("quiet");
    // A closed microphone does not hide the agent speaking.
    expect(waveVisual("agent", false)).toBe("agent");
  });
});

describe("barTarget", () => {
  it("raises the bars with the level of whoever speaks, most in the centre", () => {
    for (const visual of ["user", "agent", "interrupted", "listening"] as WaveVisual[]) {
      const quiet = barTarget(visual, 10, 21, 0, SILENT, 1);
      const centre = barTarget(visual, 10, 21, 0, LOUD, 1);
      const edge = barTarget(visual, 0, 21, 0, LOUD, 1);
      expect(centre, visual).toBeGreaterThan(quiet);
      expect(centre, visual).toBeGreaterThan(edge);
    }
  });

  it("moves the working looks without any level", () => {
    for (const visual of ["thinking", "tool", "connecting", "approval"] as WaveVisual[]) {
      const heights = [0, 400, 800].map((t) => barTarget(visual, 10, 21, t, SILENT, 0.5));
      expect(new Set(heights).size, visual).toBeGreaterThan(1);
    }
  });

  it("marks every sixth bar while a tool runs, and lights only the centre while connecting", () => {
    expect(barTarget("tool", 6, 21, 1e6, SILENT, 0)).toBeGreaterThan(
      barTarget("tool", 7, 21, 1e6, SILENT, 0),
    );
    expect(barTarget("connecting", 0, 21, 0, SILENT, 0)).toBe(0.03);
  });

  it("holds the quiet bars flat, and a single bar sits in the centre", () => {
    expect(barTarget("quiet", 3, 21, 999, LOUD, 1)).toBe(0.035);
    expect(barTarget("user", 0, 1, 0, LOUD, 1)).toBeCloseTo(1.06);
  });
});

describe("easeBar", () => {
  it("rises quickly and falls slowly", () => {
    expect(easeBar(0, 1)).toBeCloseTo(0.4);
    expect(easeBar(1, 0)).toBeCloseTo(0.86);
  });
});

describe("agentShare", () => {
  it("colours the bars as the agent's while it speaks, or while it is still heard over the caller", () => {
    expect(agentShare("agent", SILENT)).toBe(1);
    expect(agentShare("interrupted", { input: 0, output: 0.5 })).toBe(1);
    expect(agentShare("interrupted", { input: 0.5, output: 0.5 })).toBe(0);
    expect(agentShare("user", LOUD)).toBe(0);
  });
});
