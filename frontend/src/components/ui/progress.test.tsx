import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Progress } from "./progress";

describe("Progress feedback", () => {
  it("reports the same fraction that the bar displays for a custom maximum", () => {
    render(<Progress aria-label="Uploading" value={20} max={80} />);
    const progress = screen.getByRole("progressbar", { name: "Uploading" });
    expect(progress).toHaveAttribute("aria-valuenow", "20");
    expect(progress).toHaveAttribute("aria-valuemax", "80");
    expect(progress.firstElementChild).toHaveStyle({ transform: "translateX(-75%)" });
  });

  it("distinguishes an unknown measurement from zero and completion", () => {
    const { rerender } = render(<Progress aria-label="Uploading" />);
    const progress = screen.getByRole("progressbar");
    expect(progress).not.toHaveAttribute("aria-valuenow");
    expect(progress).toHaveAttribute("data-state", "indeterminate");
    rerender(<Progress aria-label="Uploading" value={0} />);
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(progress).toHaveAttribute("data-state", "loading");
    rerender(<Progress aria-label="Uploading" value={100} />);
    expect(progress).toHaveAttribute("aria-valuenow", "100");
    expect(progress).toHaveAttribute("data-state", "complete");
  });

  it("keeps out-of-range or unavailable measurements inside its contract", () => {
    const { rerender } = render(<Progress value={120} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    rerender(<Progress value={-10} max={-1} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "100");
    rerender(<Progress value={NaN} />);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
});
