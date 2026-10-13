import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlanChecklist } from "./plan-checklist";
import type { PlanStep, PlanStepStatus } from "@/lib/plan-state";
import messages from "@/../messages/en.json";

/** Answer `prefers-reduced-motion: reduce` for the rest of the test. */
function stopMotion(): void {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

afterEach(() => vi.restoreAllMocks());

function step(status: PlanStepStatus, content = "Read the handbook", id = "s1"): PlanStep {
  return { id, content, status };
}

function draw(steps: PlanStep[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <PlanChecklist steps={steps} />
    </NextIntlClientProvider>,
  );
}

describe("PlanChecklist - where the agent is, one row per step", () => {
  it("draws every step it is given, in the order it was given them", () => {
    // Nothing reorders. The order *is* the plan, and sinking finished rows to
    // the bottom - which is what an interactive task list does - would rewrite
    // the thing being reported.
    draw([
      step("completed", "First", "a"),
      step("in_progress", "Second", "b"),
      step("pending", "Third", "c"),
    ]);

    const rows = screen.getAllByRole("listitem").map((row) => row.textContent);
    expect(rows).toEqual(["First", "Second", "Third"]);
  });

  it("names each status for anyone who cannot see the glyph", () => {
    draw([
      step("pending", "P", "a"),
      step("in_progress", "I", "b"),
      step("completed", "C", "c"),
      step("cancelled", "X", "d"),
      step("blocked", "B", "e"),
    ]);

    for (const label of ["Not started", "In progress", "Done", "Cancelled", "Blocked"]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("strikes a completed step through and a cancelled one too", () => {
    // The rule is drawn on the text rather than applied to it, so this is the
    // width it has been swept to rather than a `line-through` class.
    const { rerender } = draw([step("completed")]);
    expect(screen.getByText("Read the handbook")).toHaveStyle({ backgroundSize: "100% 1px" });

    rerender(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PlanChecklist steps={[step("cancelled")]} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Read the handbook")).toHaveStyle({ backgroundSize: "100% 1px" });
  });

  it("leaves a step that has not finished unstruck", () => {
    draw([step("in_progress")]);
    expect(screen.getByText("Read the handbook")).toHaveStyle({ backgroundSize: "0% 1px" });
  });

  it("still draws the plan with motion turned down", () => {
    // `prefers-reduced-motion` is set by people for whom a sweeping rule and a
    // drawing tick are a symptom. The checklist has to say the same thing
    // without either.
    stopMotion();
    draw([step("completed", "Done", "a"), step("pending", "Next", "b")]);

    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText("Next")).toBeInTheDocument();
    expect(screen.getByLabelText("Done")).toBeInTheDocument();
  });

  it("draws a step the tool gave no id, keyed on where it sits instead", () => {
    // `write_plan` sends the whole ordered list every time and a granular call
    // can answer without ids at all, so a missing one is a shape to draw
    // rather than a row to drop.
    draw([
      { content: "No id here", status: "pending" } as PlanStep,
      { content: "Nor here", status: "pending" } as PlanStep,
    ]);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("draws nothing at all for an empty plan", () => {
    draw([]);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
  });
});
