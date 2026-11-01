import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DateCell } from "./date-cell";

describe("DateCell", () => {
  it("renders the stored value", () => {
    render(<DateCell value="2026-09-23" onChange={vi.fn()} />);
    expect(screen.getByDisplayValue("2026-09-23")).toBeInTheDocument();
  });

  it("renders empty for null", () => {
    render(<DateCell id="due" value={null} onChange={vi.fn()} />);
    expect(document.getElementById("due")).toHaveValue("");
  });

  it("reports a chosen date", () => {
    const onChange = vi.fn();
    render(<DateCell id="due" value={null} onChange={onChange} />);
    const input = document.getElementById("due") as HTMLInputElement;

    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, "2026-09-23");
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(onChange).toHaveBeenCalledWith("2026-09-23");
  });

  it("reports null when cleared", async () => {
    const onChange = vi.fn();
    render(<DateCell id="due" value="2026-09-23" onChange={onChange} />);
    const input = document.getElementById("due") as HTMLInputElement;

    input.focus();
    // Simulate the browser clearing the field.
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, "");
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("is disabled when asked", () => {
    render(<DateCell value={null} onChange={vi.fn()} disabled />);
    expect(screen.getByDisplayValue("")).toBeDisabled();
  });
});
