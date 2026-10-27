import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { arm, comparison, evalRun, FLIP, SUMMARY } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalRun, EvalComparison } from "@/types/eval-runs";
import { AttemptRow, RoundResults } from "./round-results";
import { ReadOnlyProvider } from "./read-only";
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
  state.estimateAttribution.isPending = state.attribute.isPending = false;
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
  expect(screen.getByRole("img", { name: "3 → 4 of 4 questions handled well." })).toHaveTextContent(
    "4 of 4",
  );
  expect(
    screen.getByRole("img", {
      name: "Questions not used to write the changes: 1 → 2 of 2 handled well.",
    }),
  ).toHaveTextContent("1 of 2");
  expect(screen.queryByText(/Cost per answer/)).toBeNull();
  await userEvent.click(screen.getByText("Earlier checks"));
  expect(screen.getByRole("link", { name: "Earlier check 2" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/old",
  );
  expect(state.read).toHaveBeenCalledWith("main");
  expect(state.read).not.toHaveBeenCalledWith("first");
});
it("says why the bars and the counts differ, and shows a cost that moved on the result", () => {
  state.compared = comparison({
    cases: [
      { ...FLIP, case_id: "a", flip: "fixed", confirmed: true },
      { ...FLIP, case_id: "b", flip: "fixed", confirmed: false },
      { ...FLIP, case_id: "c", flip: "regression", confirmed: false },
    ],
    baseline_summary: SUMMARY,
    candidate_summary: { ...SUMMARY, cost_usd: "0.080000" },
  });
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  expect(
    screen.getByText(
      /^The bars count every answer graded as good\. Fixed and broken count only the answers that changed the same way when asked again; 2 changed, but not consistently\./,
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/Cost per answer/)).toHaveLength(1);
  state.compared = comparison({ cases: [], baseline_summary: null });
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.queryByText(/Cost per answer/)).not.toBeInTheDocument();
  expect(screen.queryByText(/The bars count/)).not.toBeInTheDocument();
});
it("does not request older round details until they are opened", async () => {
  render(<AttemptRow session={SESSION} round={ROUND} />);
  expect(state.read).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("Attempt 1 of 3"));
  await waitFor(() => expect(state.read).toHaveBeenCalledWith("main"));
});
it("names a round past the attempt limit for what it is, not as one more attempt", () => {
  render(
    <AttemptRow
      session={SESSION}
      round={{ ...ROUND, number: SESSION.max_iterations + 1, verdict: null }}
    />,
  );
  expect(screen.getByText("Changes held back for another attempt, not tested")).toBeInTheDocument();
  expect(screen.queryByText(/of 3$/)).toBeNull();
});
it("offers to test each change, with its price, once the details are opened", async () => {
  render(<RoundResults session={SESSION} round={ROUND} />);
  expect(state.estimateAttribution.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("Show details"));
  expect(state.estimateAttribution.mutateAsync).toHaveBeenCalledWith(1);
  expect(await screen.findByRole("heading", { name: "Which change helped?" })).toBeVisible();
  expect(
    screen.getByText(
      /^This attempt has 2 changes\. We can test each one separately .* It costs about \$0\.02 from this session's limit\.$/,
    ),
  ).toBeInTheDocument();
  expect(state.attribute.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Test each change" }));
  expect(state.attribute.mutateAsync).toHaveBeenCalledWith({ number: 1, estimate: "0.02" });
});
it("asks nothing about which change helped when the attempt made only one", async () => {
  state.estimateAttribution.mutateAsync.mockResolvedValue({ ...QUOTE, changes: 1 });
  render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByText("Show details"));
  await waitFor(() => expect(state.estimateAttribution.mutateAsync).toHaveBeenCalled());
  expect(screen.queryByText("Which change helped?")).toBeNull();
});
it("holds back testing each change over the limit, and says when the price cannot be read", async () => {
  state.estimateAttribution.mutateAsync.mockResolvedValue({ ...QUOTE, affordable: false });
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByText("Show details"));
  expect(await screen.findByRole("button", { name: "Test each change" })).toBeDisabled();
  expect(screen.getByText("That is more than this session has left.")).toBeInTheDocument();
  view.unmount();
  state.estimateAttribution.mutateAsync.mockRejectedValue(new Error("Unavailable"));
  render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByText("Show details"));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});
it("reports a failed start of the per-change checks", async () => {
  state.attribute.mutateAsync.mockRejectedValue(new Error("The base changed"));
  render(<RoundResults session={SESSION} round={ROUND} />);
  await userEvent.click(screen.getByText("Show details"));
  await userEvent.click(await screen.findByRole("button", { name: "Test each change" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The base changed");
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
it("keeps the measurement in the one Show details and identifies a human re-evaluation", async () => {
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
  expect(screen.getAllByText("Show details")).toHaveLength(1);
  await userEvent.click(screen.getByText("Show details"));
  expect(screen.getByRole("heading", { name: "How we measured it" })).toBeInTheDocument();
  expect(
    screen.getByText(
      "Of the 2 test questions, 1 was shown to the helper while it wrote the changes. The other 1 was kept aside, and only they decide the result, so the changes cannot just learn the answers.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("Selected attempt")).toBeNull();
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
it("sums an attempt up by its change against its own baseline, and marks the best one", () => {
  const view = render(
    <AttemptRow
      session={SESSION}
      round={{
        ...ROUND,
        verdict_detail: {
          fixed: 3,
          broken: 1,
          held_out: 6,
          baseline_pass_rate: 0.5,
          candidate_pass_rate: 0.8,
        },
      }}
    />,
  );
  const row = screen.getByText("Attempt 1 of 3").closest("summary")!;
  expect(row).toHaveTextContent("Better");
  expect(row).toHaveTextContent("+3 fixed · 1 broken of 6 kept aside");
  expect(row).not.toHaveTextContent("50%");
  expect(row).toHaveTextContent("$0.03");
  expect(row).toHaveTextContent("Best attempt");
  expect(row.closest("details")).not.toHaveAttribute("open");
  view.rerender(
    <AttemptRow session={SESSION} round={{ ...ROUND, verdict_detail: { fixed: 2, broken: 0 } }} />,
  );
  expect(screen.getByText("Attempt 1 of 3").closest("summary")).toHaveTextContent(
    /\+2 fixed · 0 broken(?! of)/,
  );
});
it("distinguishes a worse attempt from a mixed one", () => {
  const view = render(
    <AttemptRow
      session={SESSION}
      round={{ ...ROUND, id: "r2", verdict: "regression", verdict_detail: { fixed: 0, broken: 2 } }}
    />,
  );
  expect(screen.getByText("Worse")).toHaveClass("bg-destructive/10");
  expect(screen.queryByText("Best attempt")).toBeNull();
  view.rerender(
    <AttemptRow
      session={SESSION}
      round={{ ...ROUND, verdict: "regression", verdict_detail: { fixed: 1, broken: 2 } }}
    />,
  );
  expect(screen.getByText("Mixed")).toHaveClass("bg-warning/10");
});
it.each([
  ["running", "b1", "Working"],
  ["stopped", "b1", "Not measured"],
  ["stopped", null, "No changes"],
] as const)("names an unmeasured attempt of a %s session for what it is", (status, batch, pill) => {
  render(
    <AttemptRow
      session={{ ...SESSION, status }}
      round={{ ...ROUND, verdict: null, verdict_detail: null, batch_id: batch, eval_run_ids: [] }}
    />,
  );
  expect(screen.getByText(pill)).toBeInTheDocument();
  expect(screen.queryByText(/fixed ·/)).toBeNull();
});
it("keeps an automatic repeat in history", async () => {
  render(
    <RoundResults
      session={SESSION}
      round={{ ...ROUND, verdict_detail: null, eval_run_ids: ["first", "main"] }}
    />,
  );
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

it("offers no paid check once the wizard is only read", () => {
  render(
    <ReadOnlyProvider value="finished">
      <RoundResults session={{ ...SESSION, status: "stopped" }} round={ROUND} />
    </ReadOnlyProvider>,
  );
  expect(
    screen.queryByRole("button", { name: "Estimate individual checks" }),
  ).not.toBeInTheDocument();
});
const event = (action: string, at: string) => ({
  action,
  at,
  stage: null,
  status: null,
  reason: null,
});

it("calls an attempt that was not better chosen only once a person chose it, never best", () => {
  const round = {
    ...ROUND,
    verdict: "regression" as const,
    verdict_detail: { fixed: 0, broken: 2 },
  };
  const verdict = event("improvement.verdict", "2026-10-27T15:59:40Z");
  const view = render(<AttemptRow session={{ ...SESSION, timeline: [verdict] }} round={round} />);
  expect(screen.queryByText("Chosen attempt")).toBeNull();
  const chose = event("improvement.round_selected", "2026-10-27T16:03:54Z");
  view.rerender(<AttemptRow session={{ ...SESSION, timeline: [verdict, chose] }} round={round} />);
  expect(screen.getByText("Chosen attempt")).toBeInTheDocument();
  expect(screen.queryByText("Best attempt")).toBeNull();
});

it("forgets a choice made before a later verdict", () => {
  render(
    <AttemptRow
      session={{
        ...SESSION,
        timeline: [
          event("improvement.round_selected", "2026-10-27T16:00:00Z"),
          event("improvement.verdict", "2026-10-27T16:10:00Z"),
        ],
      }}
      round={{ ...ROUND, verdict: "no_change", verdict_detail: { fixed: 0, broken: 0 } }}
    />,
  );
  expect(screen.queryByText("Chosen attempt")).toBeNull();
});

const afterBar = (name: RegExp) =>
  screen.getByRole("img", { name }).querySelectorAll("span.rounded-full span")[1];

it("colours a bar only for a confirmed change, and calls opposite bars within noise", () => {
  state.run = evalRun({
    arms: [
      arm({ id: "base", role: "baseline" }),
      arm({ id: "candidate", summary: { ...SUMMARY, passed: 1 } }),
    ],
  });
  state.compared = comparison({
    cases: [],
    regressions_confirmed: 0,
    baseline_summary: { ...SUMMARY, cases: 10, passed: 5 },
    candidate_summary: { ...SUMMARY, cases: 10, passed: 6 },
  });
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  expect(afterBar(/^3 → 1 of 4/)).toHaveClass("bg-muted-foreground/50");
  expect(afterBar(/^Questions not used/)).toHaveClass("bg-muted-foreground/50");
  expect(
    screen.getByText(
      "The two bars point in opposite directions, so the difference is within noise.",
    ),
  ).toBeInTheDocument();
  state.compared = comparison({
    cases: [],
    regressions_confirmed: 1,
    baseline_summary: { ...SUMMARY, cases: 10, passed: 6 },
    candidate_summary: { ...SUMMARY, cases: 10, passed: 5 },
  });
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(afterBar(/^Questions not used/)).toHaveClass("bg-destructive");
  expect(screen.queryByText(/within noise/)).toBeNull();
  state.compared = comparison({
    cases: [],
    regressions_confirmed: 0,
    fixed_confirmed: 1,
    baseline_summary: { ...SUMMARY, cases: 10, passed: 5 },
    candidate_summary: { ...SUMMARY, cases: 10, passed: 6 },
  });
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(afterBar(/^Questions not used/)).toHaveClass("bg-success");
});

it("calls a one-question difference within noise, and a larger one too on a noisy test", () => {
  state.compared = comparison({
    cases: [],
    regressions_confirmed: 0,
    baseline_summary: { ...SUMMARY, cases: 10, passed: 5 },
    candidate_summary: { ...SUMMARY, cases: 10, passed: 6 },
  });
  const view = render(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.getByText("A difference of one question is within noise.")).toBeInTheDocument();
  state.run = evalRun({
    arms: [
      arm({ id: "base", role: "baseline" }),
      arm({ id: "candidate", summary: { ...SUMMARY, passed: 1 } }),
    ],
  });
  state.compared = comparison({
    cases: [],
    regressions_confirmed: 0,
    baseline_summary: { ...SUMMARY, cases: 10, passed: 7 },
    candidate_summary: { ...SUMMARY, cases: 10, passed: 5 },
  });
  const noisy = {
    ...SESSION,
    measurement_noise: {
      noisy: true,
      held_out: 10,
      baseline_low: 0.5,
      baseline_high: 0.7,
      baseline_spread: 2,
      unstable: 6,
      within: 6,
      shared: 10,
      between: 2,
      too_few_shared: false,
      by_attempt: [],
      examples: [],
    },
  };
  view.rerender(<RoundResults session={SESSION} round={ROUND} />);
  expect(screen.queryByText(/within noise|may be noise/)).toBeNull();
  view.rerender(<RoundResults session={noisy} round={ROUND} />);
  expect(
    screen.getByText("This session's test is noisy, so a difference this small may be noise."),
  ).toBeInTheDocument();
});
