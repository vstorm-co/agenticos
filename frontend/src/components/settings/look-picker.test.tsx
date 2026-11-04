import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LookPicker } from "./look-picker";

describe("LookPicker", () => {
  it("offers every look as a radio, with the chosen one checked", () => {
    render(<LookPicker labelledBy="x" value="graphite" dark={false} onChange={() => {}} />);
    expect(screen.getAllByRole("radio")).toHaveLength(5);
    expect(screen.getByRole("radio", { name: /Graphite/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Glass/ })).not.toBeChecked();
  });

  it("picks on click, and moves and picks with the arrow keys, wrapping round", async () => {
    const onChange = vi.fn();
    render(<LookPicker labelledBy="x" value="standard" dark onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: /Paper/ }));
    expect(onChange).toHaveBeenLastCalledWith("paper");

    screen.getByRole("radio", { name: /Standard/ }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("paper");
    expect(screen.getByRole("radio", { name: /Paper/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onChange).toHaveBeenLastCalledWith("standard");
    await userEvent.keyboard("a");
    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it("checks nothing before the stored look is known", () => {
    render(<LookPicker labelledBy="x" value={undefined} dark={false} onChange={() => {}} />);
    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Standard/ })).toHaveAttribute("tabindex", "0");
  });
});
