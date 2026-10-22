import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CadenceChoices, chosenCadence, isWorkdays, type CadenceShape } from "./cadence-choices";

/**
 * How often a schedule runs, asked first as one of a few or Custom: the
 * controls a template or an existing schedule filled in land on the choice
 * they amount to.
 */

const DAILY: CadenceShape = {
  scheduleKind: "cron",
  intervalUnit: "hours",
  intervalCount: "1",
  cronFreq: "daily",
  cronWeekdays: [1],
};

describe("chosenCadence", () => {
  it.each([
    [{ scheduleKind: "interval", intervalUnit: "minutes", intervalCount: "15" }, "every15m"],
    [{ scheduleKind: "interval", intervalUnit: "hours", intervalCount: "1" }, "hourly"],
    [{ scheduleKind: "interval", intervalUnit: "hours", intervalCount: "6" }, "every6h"],
    [{ scheduleKind: "interval", intervalUnit: "hours", intervalCount: "3" }, "custom"],
    [{ scheduleKind: "interval", intervalUnit: "days", intervalCount: "2" }, "custom"],
    [{}, "daily"],
    [{ cronFreq: "weekly", cronWeekdays: [5, 4, 3, 2, 1] }, "weekdays"],
    [{ cronFreq: "weekly", cronWeekdays: [1, 3] }, "weekly"],
    [{ cronFreq: "monthly" }, "custom"],
    [{ cronFreq: "advanced" }, "custom"],
  ] as const)("reads %j as %s", (overrides, choice) => {
    expect(chosenCadence({ ...DAILY, ...overrides })).toBe(choice);
  });

  it("counts only Monday to Friday as workdays", () => {
    expect(isWorkdays([1, 2, 3, 4, 5])).toBe(true);
    expect(isWorkdays([1, 2, 3, 4, 5, 6])).toBe(false);
  });
});

describe("CadenceChoices", () => {
  it("checks the current choice and hands back the one picked", async () => {
    const onChange = vi.fn();
    render(<CadenceChoices value="weekdays" onChange={onChange} />);

    expect(screen.getByRole("radiogroup", { name: "How often" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Weekdays" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Daily" })).toHaveAttribute("aria-checked", "false");

    await userEvent.click(screen.getByRole("radio", { name: "Custom" }));
    expect(onChange).toHaveBeenCalledWith("custom");
  });
});
