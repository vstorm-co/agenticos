import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WizardSteps } from "./wizard-steps";

const STEPS = [
  { id: "source", label: "Pick source" },
  { id: "configure", label: "Configure" },
  { id: "schedule", label: "Schedule" },
];

describe("the wizard's steps", () => {
  it("marks the step on screen, checks the ones behind it and numbers the rest", () => {
    const { container } = render(<WizardSteps steps={STEPS} current="configure" />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[0]).not.toHaveAttribute("aria-current");
    // The finished step shows a check rather than its number; the next shows "3".
    expect(items[0]?.querySelector("svg")).not.toBeNull();
    expect(items[2]).toHaveTextContent("3");
    expect(screen.getByText("Configure")).toHaveClass("text-foreground");
    expect(container.querySelector(".uppercase")).toBeNull();
  });

  it("names every step in words, as written", () => {
    render(<WizardSteps steps={STEPS} current="source" />);

    expect(screen.getByText("Pick source")).toBeInTheDocument();
    expect(screen.getByText("Schedule")).toBeInTheDocument();
  });
});
