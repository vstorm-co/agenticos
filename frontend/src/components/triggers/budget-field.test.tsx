import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BudgetField, parseBudget } from "./budget-field";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

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
