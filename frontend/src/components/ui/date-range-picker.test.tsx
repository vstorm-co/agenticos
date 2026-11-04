import { fireEvent, render, screen } from "@testing-library/react";
import * as intl from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DateRangePicker } from "./date-range-picker";

afterEach(() => vi.restoreAllMocks());

describe("DateRangePicker", () => {
  it("two clicks pick a range, whichever order they land in", () => {
    const onChange = vi.fn();
    render(<DateRangePicker value={null} onChange={onChange} maxDate="2026-08-05" />);

    fireEvent.click(screen.getByRole("button", { name: "2026-07-20" }));
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "2026-07-05" }));
    expect(onChange).toHaveBeenCalledWith({ from: "2026-07-05", to: "2026-07-20" });
  });

  it("shows the picked range as pressed cells", () => {
    render(
      <DateRangePicker
        value={{ from: "2026-07-05", to: "2026-07-07" }}
        onChange={vi.fn()}
        maxDate="2026-08-05"
      />,
    );

    expect(screen.getByRole("button", { name: "2026-07-06" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "2026-07-10" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("a day after maxDate cannot be picked", () => {
    render(
      <DateRangePicker
        value={{ from: "2026-08-01", to: "2026-08-05" }}
        onChange={vi.fn()}
        maxDate="2026-08-05"
      />,
    );

    expect(screen.getByRole("button", { name: "2026-08-06" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "2026-08-05" })).toBeEnabled();
  });

  it("cannot scroll past the last pickable month", () => {
    render(
      <DateRangePicker
        value={{ from: "2026-08-01", to: "2026-08-05" }}
        onChange={vi.fn()}
        maxDate="2026-08-05"
      />,
    );

    // Opens on July+August with August the last pickable month.
    expect(screen.getByRole("button", { name: "Next months" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous months" }));
    expect(screen.getByRole("button", { name: "Next months" })).toBeEnabled();
  });
  it("uses the console language for month names and weekdays", () => {
    vi.spyOn(intl, "useLocale").mockReturnValue("pl");
    render(<DateRangePicker value={null} onChange={vi.fn()} maxDate="2026-08-05" />);
    expect(screen.getByText("lipiec 2026")).toBeVisible();
    expect(screen.getByText("sierpień 2026")).toBeVisible();
    expect(screen.getAllByText("pon.")).toHaveLength(2);
    expect(screen.queryByText("Mon")).not.toBeInTheDocument();
  });
});
