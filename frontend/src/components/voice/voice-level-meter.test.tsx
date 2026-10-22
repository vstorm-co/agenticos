import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useMotionStore } from "@/stores";

import { meterStep, VoiceLevelMeter } from "./voice-level-meter";

afterEach(() => useMotionStore.setState({ motion: "system" }));

describe("VoiceLevelMeter", () => {
  it.each([
    [0, 0],
    [0.05, 0],
    [0.2, 1],
    [0.5, 3],
    [1, 5],
    [2, 5],
  ])("maps level %s to step %s", (level, step) => {
    expect(meterStep(level)).toBe(step);
  });

  it("follows the real level, as a stepped meter, and stays still under reduced motion", () => {
    useMotionStore.setState({ motion: "reduce" });
    render(<VoiceLevelMeter level={0.5} label="Agent speaking" tone="agent" />);
    const meter = screen.getByRole("meter", { name: "Agent speaking" });
    expect(meter).toHaveAttribute("aria-valuenow", "3");
    expect(meter).toHaveAttribute("data-motion", "reduced");
  });

  it("eases between steps when motion is welcome", () => {
    useMotionStore.setState({ motion: "full" });
    render(<VoiceLevelMeter level={0.2} label="You" tone="caller" />);
    const meter = screen.getByRole("meter", { name: "You" });
    expect(meter).toHaveAttribute("data-motion", "full");
    expect(meter.querySelectorAll(".opacity-100")).toHaveLength(1);
  });
});
