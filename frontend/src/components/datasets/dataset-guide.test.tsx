import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { datasetFixture as dataset } from "@/test-utils/datasets";
import { DatasetGuide } from "./dataset-guide";
import { datasetNextStep } from "./dataset-journey";

const configured = () =>
  dataset({ scoring: { ...DEFAULT_SCORING, reference: { enabled: true, required: true } } });

describe("dataset journey", () => {
  it("starts with cases, and requires actual grading coverage before recommending evals", () => {
    expect(datasetNextStep(dataset({ case_count: 0 }))).toBe("cases");
    expect(datasetNextStep(dataset())).toBe("grading");
    expect(datasetNextStep(configured())).toBe("evals");
    expect(
      datasetNextStep(
        dataset({
          scoring: { ...DEFAULT_SCORING, judge: { ...DEFAULT_SCORING.judge, enabled: true } },
        }),
      ),
    ).toBe("grading");
  });

  it("opens the next step through the page navigation and marks the current step", async () => {
    const onTab = vi.fn();
    render(<DatasetGuide dataset={dataset()} tab="cases" canViewRuns onTab={onTab} />);
    expect(screen.getByRole("button", { name: /1. Add cases/ })).toHaveAttribute(
      "aria-current",
      "step",
    );
    await userEvent.click(screen.getByRole("button", { name: "Set up grading" }));
    expect(onTab).toHaveBeenCalledWith("grading");
    await userEvent.click(screen.getByRole("button", { name: /4. Review results/ }));
    expect(onTab).toHaveBeenLastCalledWith("review");
    await userEvent.click(screen.getByRole("button", { name: "Your dataset, step by step" }));
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("Set up grading")).toBeInTheDocument();
  });

  it("does not offer an eval route without run visibility or a run action without permission", () => {
    const { rerender } = render(
      <DatasetGuide dataset={configured()} tab="grading" canViewRuns={false} onTab={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /Test an agent/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open evals" })).toBeNull();
    rerender(
      <DatasetGuide
        dataset={{ ...configured(), can_run: false }}
        tab="grading"
        canViewRuns
        onTab={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Test an agent/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open evals" })).toBeNull();
  });
});
