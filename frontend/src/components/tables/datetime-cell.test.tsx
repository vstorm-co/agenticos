import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatetimeCell } from "./datetime-cell";

function setValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

/** The local wall-clock string a `datetime-local` input shows for an ISO instant, in this machine's own time zone - mirrors the component's own conversion so the test does not hardcode an offset. */
function localValue(isoUtc: string): string {
  const date = new Date(isoUtc);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
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

  it("writes nothing when blurred without a change", () => {
    // Closing the record sheet blurs whatever field has focus; an untouched
    // datetime used to write its stored value back on that blur.
    const onChange = vi.fn();
    render(<DatetimeCell id="placed" value="2026-09-23T10:30:00.000Z" onChange={onChange} />);
    const input = document.getElementById("placed") as HTMLInputElement;

    fireEvent.blur(input);

    expect(onChange).not.toHaveBeenCalled();
  });

  it("is disabled when asked", () => {
    render(<DatetimeCell id="placed" value={null} onChange={vi.fn()} disabled />);
    expect(document.getElementById("placed")).toBeDisabled();
  });

  it("resyncs to a new value prop, rather than keeping a previous record's local draft", () => {
    // `record-detail-sheet.tsx` keys its editors by column id, not by
    // record id, so this component stays mounted across a record switch -
    // the regression this guards is the open record changing (or a
    // conflict's "discard"/"reload and reapply" landing) while this cell
    // silently kept showing, and would have gone on submitting, the value
    // it was first mounted with.
    const first = "2026-09-23T10:30:00.000Z";
    const second = "2026-10-01T08:00:00.000Z";
    const { rerender } = render(<DatetimeCell id="placed" value={first} onChange={vi.fn()} />);
    expect(document.getElementById("placed")).toHaveValue(localValue(first));

    rerender(<DatetimeCell id="placed" value={second} onChange={vi.fn()} />);

    expect(document.getElementById("placed")).toHaveValue(localValue(second));
  });

  it("does not stomp on an in-progress edit on a render the value prop did not change", () => {
    const onChange = vi.fn();
    const { rerender } = render(<DatetimeCell id="placed" value={null} onChange={onChange} />);
    const input = document.getElementById("placed") as HTMLInputElement;
    setValue(input, "2026-09-23T10:30");

    // A re-render with the same `value` prop - e.g. the parent re-rendering
    // for an unrelated reason - must not overwrite what is being typed.
    rerender(<DatetimeCell id="placed" value={null} onChange={onChange} />);

    expect(input).toHaveValue("2026-09-23T10:30");
  });
});
