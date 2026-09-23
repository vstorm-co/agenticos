import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatetimeCell } from "./datetime-cell";

function setValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("DatetimeCell", () => {
  it("renders empty for null", () => {
    render(<DatetimeCell id="placed" value={null} onChange={vi.fn()} />);
    expect(document.getElementById("placed")).toHaveValue("");
  });

  it("renders an invalid stored value as empty", () => {
    render(<DatetimeCell id="placed" value="not-a-date" onChange={vi.fn()} />);
    expect(document.getElementById("placed")).toHaveValue("");
  });

  it("converts the browser's local wall-clock value to UTC ISO only on blur", () => {
    const onChange = vi.fn();
    render(<DatetimeCell id="placed" value={null} onChange={onChange} />);
    const input = document.getElementById("placed") as HTMLInputElement;

    setValue(input, "2026-09-23T10:30");
    // Not yet converted - onChange fires on blur, not on every keystroke.
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledTimes(1);
    const [sent] = onChange.mock.calls[0] as [string];
    expect(new Date(sent).getTime()).toBe(new Date("2026-09-23T10:30").getTime());
  });

  it("reports null when the field is cleared and blurred", () => {
    const onChange = vi.fn();
    render(<DatetimeCell id="placed" value="2026-09-23T10:30:00.000Z" onChange={onChange} />);
    const input = document.getElementById("placed") as HTMLInputElement;

    setValue(input, "");
    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("is disabled when asked", () => {
    render(<DatetimeCell id="placed" value={null} onChange={vi.fn()} disabled />);
    expect(document.getElementById("placed")).toBeDisabled();
  });
});
