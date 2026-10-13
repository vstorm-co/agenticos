import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { progressOf, type PlanStep } from "@/lib/plan-state";

import { PlanStrip } from "./plan-strip";

/**
 * The plan, above the composer.
 *
 * A plan is written in one turn and worked through over the next several, so as a
 * step in the transcript it scrolls away under the work it describes. What the
 * strip is for is the one thing that step cannot say: where the run is *now*.
 */

const STEPS: PlanStep[] = [
  { id: "a", content: "Read the diff", status: "completed" },
  { id: "b", content: "Write the test", status: "in_progress" },
  { id: "c", content: "Push it", status: "pending" },
];

function strip(steps: PlanStep[] | null) {
  return render(<PlanStrip plan={steps === null ? null : progressOf(steps)} />);
}

describe("the plan above the composer", () => {
  it("draws nothing at all when nothing has planned", () => {
    // Every conversation renders this, and most agents never call a planning tool.
    const { container } = strip(null);

    expect(container).toBeEmptyDOMElement();
  });

  it("leads with the step in flight, not with the word Plan", () => {
    strip(STEPS);

    expect(screen.getByRole("button", { expanded: true })).toHaveTextContent("Write the test");
  });

  it("says how far along the run is, out loud as well as in the bar", () => {
    strip(STEPS);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByLabelText("1 of 3 steps completed")).toBeInTheDocument();
  });

  it("opens while there is work left, so the steps are there to read", () => {
    strip(STEPS);

    expect(screen.getByText("Push it")).toBeInTheDocument();
  });

  it("closes itself once every step is settled - a finished plan is a receipt", () => {
    strip(STEPS.map((step) => ({ ...step, status: "completed" as const })));

    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Push it")).toBeNull();
    expect(screen.getByText("Every step is done")).toBeInTheDocument();
  });

  it("lets that default be overruled either way", async () => {
    strip(STEPS);
    await userEvent.click(screen.getByRole("button", { expanded: true }));

    expect(screen.queryByText("Push it")).toBeNull();

    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("Push it")).toBeInTheDocument();
  });

  it("names each step's status for a reader who cannot see the glyph", () => {
    strip(STEPS);

    expect(screen.getByLabelText("In progress")).toBeInTheDocument();
    expect(screen.getByLabelText("Done")).toBeInTheDocument();
    expect(screen.getByLabelText("Not started")).toBeInTheDocument();
  });

  it("draws a cancelled and a blocked step as themselves", () => {
    // Both are reachable from the tools and neither is done: a blocked step waits
    // on a dependency, a cancelled one was dropped.
    strip([
      { id: "a", content: "Wait for the migration", status: "blocked" },
      { id: "b", content: "Drop the flag", status: "cancelled" },
    ]);

    expect(screen.getByLabelText("Blocked")).toBeInTheDocument();
    expect(screen.getByLabelText("Cancelled")).toBeInTheDocument();
  });

  it("falls back to naming itself when nothing is in flight yet", () => {
    strip([{ id: "a", content: "Read the diff", status: "pending" }]);

    expect(screen.getByRole("button")).toHaveTextContent("Plan");
  });
});
