import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Checkbox } from "./checkbox";

describe("Checkbox interaction", () => {
  it("lets a label toggle the whole target and announces the changed value", () => {
    const changed = vi.fn();
    render(
      <>
        <label htmlFor="include">Include archived</label>
        <Checkbox id="include" onCheckedChange={changed} />
      </>,
    );
    fireEvent.click(screen.getByText("Include archived"));
    expect(screen.getByRole("checkbox", { name: "Include archived" })).toBeChecked();
    expect(changed).toHaveBeenCalledWith(true);
  });

  it("represents a partial selection as mixed rather than checked", () => {
    render(<Checkbox aria-label="Select agents" checked="indeterminate" />);
    expect(screen.getByRole("checkbox", { name: "Select agents" })).toHaveAttribute(
      "aria-checked",
      "mixed",
    );
  });

  it("does not change a disabled selection", () => {
    const changed = vi.fn();
    render(<Checkbox aria-label="Select agents" disabled onCheckedChange={changed} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
});
