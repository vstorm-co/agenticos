import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepTimeline } from "./browser-view";
import type { Browse, BrowseStep } from "@/lib/browse";

function browse(steps: BrowseStep[], outcome: Browse["outcome"] = null): Browse {
  return {
    callId: "c1",
    goal: "",
    maxSteps: 25,
    url: null,
    title: null,
    steps,
    image: null,
    imageStep: -1,
    outcome,
    detail: null,
  };
}

const steps: BrowseStep[] = [
  { step: 1, operation: "NAVIGATE", target: "example.test", reason: "to start", url: null },
  { step: 2, operation: "SOMETHING_NEW", target: null, reason: null, url: null },
];

describe("StepTimeline - every step, with what it was for", () => {
  it("says what each step did and why, and lights the newest while the browse runs", () => {
    const { container } = render(<StepTimeline browse={browse(steps)} />);

    expect(screen.getByText("example.test")).toBeInTheDocument();
    expect(screen.getByText("to start")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(container.querySelectorAll(".bg-sky-100")).toHaveLength(1);
  });

  it("lights nothing once it is over", () => {
    const { container } = render(<StepTimeline browse={browse(steps, "done")} />);
    expect(container.querySelectorAll(".bg-sky-100")).toHaveLength(0);
  });
});
