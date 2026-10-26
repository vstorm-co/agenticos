import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { arm, comparison, evalRun, FLIP, SUMMARY } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalRun, EvalComparison } from "@/types/eval-runs";
import { RoundResults, RoundHistory } from "./round-results";
const state = vi.hoisted(() => ({
  run: null as EvalRun | null,
  compared: null as EvalComparison | null,
  runError: null as Error | null,
  comparisonError: null as Error | null,
  childRun: null as EvalRun | null,
  childCompared: null as EvalComparison | null,
  childError: null as Error | null,
  childComparisonError: null as Error | null,
  read: vi.fn(),
  compare: vi.fn(),
  estimateAttribution: { mutateAsync: vi.fn(), isPending: false },
  attribute: { mutateAsync: vi.fn(), isPending: false },
  selectRound: { mutateAsync: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-improvements", () => ({ useImprovement: () => state }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: (id: string) => {
    state.read(id);
    return id === "attr"
      ? { run: state.childRun, error: state.childError }
      : { run: state.run, error: state.runError };
  },
  useEvalComparison: (id: string, options: unknown) => {
    state.compare(id, options);
    return id === "attr"
      ? { comparison: state.childCompared, error: state.childComparisonError }
      : { comparison: state.compared, error: state.comparisonError };
  },
}));
vi.mock("./changed-answers", () => ({
  ChangedAnswers: ({ flips }: { flips: { case_id: string }[] }) => (
    <p>Changed questions: {flips.map((flip) => flip.case_id).join(", ")}</p>
  ),
}));
const ROUND = { ...SESSION.iterations[0]!, eval_run_ids: ["main"] };
const QUOTE = { changes: 2, total_usd: "0.02", affordable: true, already_started: false };
beforeEach(() => {
  vi.clearAllMocks();
  state.run = evalRun({
    arms: [
      arm({ id: "base", role: "baseline" }),
      arm({ id: "candidate", summary: { ...SUMMARY, passed: 4 } }),
    ],
  });
  state.compared = comparison({ cases: [] });
  state.runError = state.comparisonError = state.childError = state.childComparisonError = null;
  state.childRun = evalRun();
  state.childCompared = comparison();
  state.estimateAttribution.mutateAsync.mockResolvedValue(QUOTE);
  state.attribute.mutateAsync.mockResolvedValue(SESSION);
  state.selectRound.mutateAsync.mockResolvedValue(SESSION);
  state.estimateAttribution.isPending =
    state.attribute.isPending =
    state.selectRound.isPending =
      false;
});
it("shows before/after totals, independent results, cost and earlier measurement links", async () => {
  state.compared = comparison({
    cases: [],
    baseline_summary: { ...SUMMARY, cases: 2, passed: 1 },
    candidate_summary: { ...SUMMARY, cases: 2, passed: 2 },
  });
  render(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, eval_run_ids: ["first", "main"], previous_eval_run_ids: ["old"] }}
    />,
  );
  expect(screen.getByText("3 → 4 of 4 questions handled well.")).toBeInTheDocument();
  expect(
    screen.getByText("Questions not used to write the changes: 1 → 2 of 2 handled well."),
  ).toBeInTheDocument();
  expect(screen.getByText(/Cost per answer/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("Earlier checks"));
  expect(screen.getByRole("link", { name: "Earlier check 2" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/old",
  );
  expect(state.read).toHaveBeenCalledWith("main");
  expect(state.read).not.toHaveBeenCalledWith("first");
});
it("does not request older round details until they are opened", async () => {
  render(<RoundHistory session={SESSION} round={ROUND} />);
  expect(state.read).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("Attempt 1 of 3"));
  await waitFor(() => expect(state.read).toHaveBeenCalledWith("main"));
});
it("lets a stopped session review its best round and reports selection failures", async () => {
  state.selectRound.mutateAsync.mockRejectedValue(new Error("The base changed"));
  render(<RoundResults session={{ ...SESSION, status: "stopped" }} round={ROUND} />);
  await userEvent.click(screen.getByRole("button", { name: "Use this attempt" }));
  expect(state.selectRound.mutateAsync).toHaveBeenCalledWith(1);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});
it("keeps attribution behind a price and a separate confirmation", async () => {
  render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate individual checks" }));
  expect(state.attribute.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm and test each change" }),
  );
  expect(state.attribute.mutateAsync).toHaveBeenCalledWith({ number: 1, estimate: "0.02" });
});
it("disables unaffordable attribution and shows estimate errors", async () => {
  state.estimateAttribution.mutateAsync.mockResolvedValue({ ...QUOTE, affordable: false });
  render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate individual checks" }));
  expect(
    await screen.findByRole("button", { name: "Confirm and test each change" }),
  ).toBeDisabled();
  state.estimateAttribution.mutateAsync.mockRejectedValue(new Error("Unavailable"));
  await userEvent.click(screen.getByRole("button", { name: "Estimate individual checks" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});
it("shows read failures, loading and a missing comparison without fabricating changed questions", () => {
  state.runError = new Error("Forbidden");
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.runError = null;
  state.run = null;
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.run = evalRun();
  state.compared = null;
  state.comparisonError = new Error("Cannot compare");
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("keeps measurement details collapsed and identifies a human re-evaluation", async () => {
  state.run = evalRun({
    review: {
      by_user_id: "u1",
      by_name: "Ada",
      at: "2026-10-24T10:00:00Z",
      previous_verdict: "worse",
      verdict: "better",
      undo: false,
    },
    proposal_check: {
      kind: "agent",
      on_draft: true,
      suggestions: 1,
      base_version: null,
      measurement: {
        train_case_ids: ["t1"],
        holdout_case_ids: ["h1"],
        excluded_case_ids: [],
        gradable_holdout: 1,
        minimum_holdout: 5,
      },
    },
  });
  state.compared = comparison({ cases: [FLIP] });
  render(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByText(/after review by Ada/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("Show measurement details"));
  expect(screen.getByText("Changed questions: case-1")).toBeInTheDocument();
});
it.each(["queued", "running", "failed", "completed"] as const)(
  "handles %s per-change results and stops live reads after completion",
  async (status) => {
    state.childRun = evalRun({ status });
    state.childCompared = comparison({
      cases: [FLIP, { ...FLIP, case_id: "fixed", input: "Gift order?", flip: "fixed" }],
    });
    render(
      <RoundResults
        session={SESSION}
        round={{ ...ROUND, attribution_eval_run_ids: { h1: "attr" } }}
      />,
    );
    await userEvent.click(screen.getByText("Effect of change 1"));
    expect(state.compare).toHaveBeenCalledWith("attr", {
      live: status === "queued" || status === "running",
    });
    if (status === "failed")
      expect(screen.getByText(/did not produce a usable result/)).toBeInTheDocument();
    if (status === "completed") expect(screen.getByText(/Gift order/)).toBeInTheDocument();
  },
);
it("handles unavailable attribution data and comparisons", async () => {
  state.childError = new Error("Forbidden");
  const view = render(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, attribution_eval_run_ids: { h1: "attr" } }}
    />,
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.childError = null;
  state.childRun = null;
  view.rerender(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, attribution_eval_run_ids: { h1: "attr" } }}
    />,
  );
  expect(screen.getAllByText("Still working…").length).toBeGreaterThan(0);
  state.childRun = evalRun();
  state.childComparisonError = new Error("Unavailable");
  view.rerender(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, attribution_eval_run_ids: { h1: "attr" } }}
    />,
  );
  expect(screen.getByText(/did not produce a usable result/)).toBeInTheDocument();
});

it("never credits an unconfirmed attribution and explains an empty completed result", () => {
  state.childCompared = comparison({ cases: [{ ...FLIP, confirmed: false }] });
  const props = { session: SESSION, round: { ...ROUND, attribution_eval_run_ids: { h1: "attr" } } };
  const view = render(<RoundResults {...props} />);
  expect(screen.queryByText(FLIP.input, { exact: false })).not.toBeInTheDocument();
  expect(screen.getAllByText(/No changed questions/)).toHaveLength(2);
  state.childCompared = comparison({ verdict: "invalid" });
  view.rerender(<RoundResults {...props} />);
  expect(screen.getByText(/did not produce a usable result/)).toBeInTheDocument();
});

it.each(["queued", "running", "failed"] as const)(
  "never shows an unfinished %s check as a completed measurement",
  (status) => {
    state.run = evalRun({ status });
    render(<RoundResults session={SESSION} round={ROUND} />);
    expect(screen.queryByText(/Questions not used to write the changes:/)).not.toBeInTheDocument();
    expect(screen.getByRole(status === "failed" ? "alert" : "status")).toBeInTheDocument();
  },
);
it.each(["no_change", "inconclusive", "regression"] as const)(
  "shows the %s round rather than a success colour",
  (verdict) => {
    render(
      <RoundResults session={{ ...SESSION, status: "running" }} round={{ ...ROUND, verdict }} />,
    );
    expect(
      screen.queryByRole("button", { name: "Estimate individual checks" }),
    ).not.toBeInTheDocument();
  },
);
it("distinguishes a worse result from a mixed result", () => {
  const view = render(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, verdict: "regression", verdict_detail: { fixed: 0, broken: 2 } }}
    />,
  );
  expect(screen.getByText("Worse: breaks 2 questions.")).toHaveClass("text-destructive");
  view.rerender(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, verdict: "regression", verdict_detail: { fixed: 1, broken: 2 } }}
    />,
  );
  expect(screen.getByText(/Mixed:/)).toHaveClass("text-warning");
});
it.each(["running", "stopped"] as const)(
  "does not claim it is working after a round has %s",
  (status) => {
    render(
      <RoundResults
        session={{ ...SESSION, status }}
        round={{ ...ROUND, verdict: null, verdict_detail: null, eval_run_ids: [] }}
      />,
    );
    expect(
      screen.getByText(status === "running" ? "Still working…" : /did not produce a usable result/),
    ).toBeInTheDocument();
  },
);
it("does not invent missing legacy counts and keeps an automatic repeat in history", async () => {
  render(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, verdict_detail: null, eval_run_ids: ["first", "main"] }}
    />,
  );
  expect(screen.getByText("Open the full check for result details.")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Earlier checks"));
  expect(screen.getByRole("link", { name: "Earlier check 1" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/first",
  );
});
it("waits for a comparison and sends only flipped question identities to the detail view", () => {
  state.compared = null;
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText(/No changed questions/)).not.toBeInTheDocument();
  state.compared = comparison({
    cases: [
      { ...FLIP, flip: "fixed" },
      { ...FLIP, case_id: "unchanged", flip: "unchanged" },
    ],
  });
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByText("Changed questions: case-1")).toBeInTheDocument();
});
it("waits for an attribution comparison and does not credit unchanged questions", () => {
  state.childCompared = null;
  const props = { session: SESSION, round: { ...ROUND, attribution_eval_run_ids: { h1: "attr" } } };
  const view = render(<RoundResults {...props} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.childCompared = comparison({ cases: [{ ...FLIP, flip: "unchanged" }] });
  view.rerender(<RoundResults {...props} />);
  expect(screen.getAllByText(/No changed questions/)).toHaveLength(2);
});
