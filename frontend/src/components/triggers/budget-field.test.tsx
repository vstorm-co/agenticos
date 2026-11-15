import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BudgetField, parseBudget, raisesBudget } from "./budget-field";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("raisesBudget", () => {
  it.each([
    [10, 5, true],
    [null, 5, true],
    [5, 5, false],
    [2, 5, false],
    [undefined, 5, false],
    [10, null, false],
    [null, null, false],
  ])("%s against a stored cap of %s raises it: %s", (parsed, stored, expected) => {
    expect(raisesBudget(parsed, stored)).toBe(expected);
  });
});

describe("parseBudget", () => {
  it.each([
    ["5", 5],
    [" 2.5 ", 2.5],
    ["", null],
    ["0", undefined],
    ["-3", undefined],
    ["abc", undefined],
    ["Infinity", undefined],
    ["0x10", undefined],
    ["1e3", undefined],
  ])("reads %j as %j", (input, expected) => {
    expect(parseBudget(input)).toBe(expected);
  });
});

describe("BudgetField", () => {
  it("hands back what was typed and shows a refusal", () => {
    const onChange = vi.fn();
    render(<BudgetField value="" onChange={onChange} error="Too low" />);

    fireEvent.change(screen.getByLabelText("budgetLabel", { exact: false }), {
      target: { value: "7" },
    });

    expect(onChange).toHaveBeenCalledWith("7");
    expect(screen.getByText("Too low")).toBeInTheDocument();
  });
});
