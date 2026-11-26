import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { arm, comparison, SUMMARY } from "@/test-utils/eval-runs";
import type { EvalComparison } from "@/types/eval-runs";
import { ResultOverview } from "./result-overview";

describe("ResultOverview", () => {
  it("explains a single test using answer counts instead of an unexplained percentage", () => {
    render(
      <ResultOverview
        candidate={arm({ summary: { ...SUMMARY, failed: 9 } })}
        comparison={comparison({
          baseline: null,
          verdict: null,
          candidate_summary: { ...SUMMARY, cases: 12, passed: 3, failed: 9 },
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "3 of 12 answers passed" })).toBeVisible();
    expect(screen.getByText("9 answers need your review.")).toBeVisible();
    expect(screen.queryByText("Pass rate")).toBeNull();
  });
  it.each<{ change: Partial<EvalComparison>; title: string }>([
    {
      change: {
        verdict: "better",
        overall: "better",
        fixed_confirmed: 2,
        regressions_confirmed: 0,
      },
      title: "The updated agent answered better",
    },
    { change: { verdict: "worse" }, title: "Some answers got worse" },
    { change: { verdict: "mixed" }, title: "Some answers got worse" },
    {
      change: { verdict: "no_difference", overall: "worse", regressions_confirmed: 0 },
      title: "Some answers got worse",
    },
    {
      change: { verdict: "invalid", invalid_reason_code: "too_few_held_out" },
      title: "We cannot compare these results yet",
    },
    {
      change: { verdict: "invalid", invalid_reason_code: null },
      title: "We cannot compare these results yet",
    },
    {
      change: { verdict: "better", overall: null, fixed_confirmed: 0 },
      title: "No clear improvement",
    },
    { change: { verdict: null }, title: "No comparison is available yet" },
    {
      change: { verdict: "better", overall: null, candidate_summary: { ...SUMMARY, ungraded: 1 } },
      title: "Some answers could not be checked",
    },
  ])("keeps the outcome truthful: $title", ({ change, title }) => {
    render(<ResultOverview candidate={arm()} comparison={comparison(change)} />);
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
  });
  it("keeps unstable answers and missing grades explicit", () => {
    render(
      <ResultOverview
        candidate={arm()}
        comparison={comparison({
          verdict: "better",
          candidate_summary: { ...SUMMARY, ungraded: 2 },
          fixed_unconfirmed: 1,
        })}
      />,
    );
    expect(screen.getByText("2 answers could not be checked.")).toBeVisible();
    expect(screen.getByText(/Some answers varied between tests/)).toBeVisible();
  });
  it("describes gains in checking rules without claiming whole answers were fixed", () => {
    render(
      <ResultOverview
        candidate={arm()}
        comparison={comparison({
          verdict: "better",
          fixed_confirmed: 0,
          regressions_confirmed: 0,
          families: [
            {
              family: "Returns",
              criteria: [],
              cases: 12,
              baseline_passed: 1,
              candidate_passed: 12,
              fixed: 11,
              broken: 0,
              fixed_confirmed: 11,
              broken_confirmed: 0,
              p_value: 0,
              settled: true,
              better: true,
              worse: false,
            },
          ],
        })}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Answers follow more of your requirements" }),
    ).toBeVisible();
  });
});
