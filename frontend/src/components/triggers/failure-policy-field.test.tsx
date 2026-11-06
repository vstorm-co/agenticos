import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FailurePolicyField, RoutineAutoPause } from "./failure-policy-field";

describe("routine failure policy", () => {
  it("offers a bounded limit and an explicit disabled policy", async () => {
    const change = vi.fn();
    const { rerender } = render(<FailurePolicyField value={3} onChange={change} />);
    expect(screen.getByRole("combobox")).toHaveTextContent("After 3 unsuccessful checks");
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("option", { name: "Do not pause for repeated execution failures" }),
    );
    expect(change).toHaveBeenLastCalledWith(null);
    rerender(<FailurePolicyField value={null} onChange={change} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("option", { name: "After 20 unsuccessful checks" }),
    );
    expect(change).toHaveBeenLastCalledWith(20);
  });

  it("distinguishes automatic pause from an ordinary off switch", () => {
    const { rerender } = render(<RoutineAutoPause stoppedAt={null} count={0} />);
    expect(screen.queryByText(/Paused after/)).not.toBeInTheDocument();
    rerender(<RoutineAutoPause stoppedAt="2026-11-03T10:00:00Z" count={3} />);
    expect(screen.getByText("Paused after 3 unsuccessful checks")).toBeVisible();
  });
});
