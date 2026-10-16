import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CANDIDATE_ESTIMATE,
  ESTIMATE,
  SUMMARY,
  arm,
  attempt,
  comparison,
  evalRun,
} from "@/test-utils/eval-runs";
import type { PassRateLine } from "@/components/charts/pass-rate-lines.impl";
import { caseScore } from "@/test-utils/scores";
import { ArmsTable } from "./arms-table";
import { CaseDetail } from "./case-detail";
import { ComparisonCard } from "./comparison-card";
import { EstimateSummary } from "./estimate-summary";
import { EvalStatusBadge } from "./eval-status-badge";
import { EvalsPanel } from "./evals-panel";
import { VerdictChip } from "./run-row";
import { sideName } from "./names";
import { PassRateChart, passRateLines } from "./pass-rate-chart";
import { percent, seconds, usd } from "./format";

const evalRuns = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/components/charts/pass-rate-lines.impl", () => ({
  PassRateLinesImpl: ({
    lines,
    recent,
    rangeLabel,
  }: {
    lines: PassRateLine[];
    recent: number;
    rangeLabel: string;
  }) => (
    <p>{`${rangeLabel}, last ${recent}: ${lines.map((l) => `${l.key}×${l.points.length}`).join(" ")}`}</p>
  ),
}));
vi.mock("@/hooks/use-eval-runs", () => ({ useEvalRuns: () => evalRuns.value }));
const datasets = vi.hoisted(() => ({ items: [] as unknown[] }));
vi.mock("@/hooks/use-datasets", () => ({ useDatasets: () => ({ datasets: datasets.items }) }));
vi.mock("./start-eval-dialog", () => ({
  StartEvalDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <button onClick={() => onOpenChange(false)}>start-dialog</button>
  ),
}));

beforeEach(() => {
  datasets.items = [];
  evalRuns.value = { runs: [], isLoading: false, error: null, refetch: vi.fn() };
});

describe("format", () => {
  it("reads money, shares and durations, and a dash for nothing", () => {
    expect(usd("0.013333", "en")).toBe("$0.0133");
    expect(usd("12.5", "en")).toBe("$12.50");
    expect(usd(null, "en")).toBe("—");
    expect(percent(0.75, "en")).toBe("75%");
    expect(percent(null, "en")).toBe("—");
    expect(seconds(1500, "en")).toBe("1.5s");
    expect(seconds(null, "en")).toBe("—");
  });
});

describe("EvalStatusBadge", () => {
  it("names where the run is", () => {
    render(<EvalStatusBadge status="budget_exceeded" />);
    expect(screen.getByText("Out of budget")).toBeInTheDocument();
  });
});

describe("sideName", () => {
  const t = (key: string, values?: { version: number }) =>
    values ? `${key}:${values.version}` : key;

  it("names a version by its number, a draft and a proposal by what they are", () => {
    expect(sideName(arm(), t)).toBe("version:7");
    expect(sideName(arm({ source: "draft", version_number: null }), t)).toBe("draft");
    expect(sideName(arm({ source: "explicit", version_number: null }), t)).toBe("proposed");
  });
});

/** A finished run of v7 against v6 on refunds that made things worse. */
function worse(overrides: Parameters<typeof evalRun>[0] = {}) {
  return evalRun({
    arms: [arm(), arm({ id: "arm-2", model_label: "claude" })],
    outcome: {
      candidate_arm_id: "arm-1",
      verdict: "worse",
      baseline: { ...comparison().candidate, run_id: "run-0", version_number: 6 },
      regressions_confirmed: 4,
      fixed_confirmed: 0,
      candidate_pass_rate: 0.75,
      baseline_pass_rate: 1,
      overall: null,
      candidate_first_pass_rate: null,
      baseline_first_pass_rate: null,
    },
    ...overrides,
  });
}

describe("passRateLines", () => {
  const t = (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${Object.values(values).join("|")}` : key;

  it("puts finished runs in order, a line per group, each point in its verdict's colour", () => {
    const lines = passRateLines(
      [
        worse({ id: "late", created_at: "2026-10-15T10:00:00Z" }),
        evalRun({
          id: "early",
          arms: [arm({ source: "draft", version_number: null })],
          outcome: { ...worse().outcome!, verdict: "better", baseline: null },
        }),
        evalRun({ id: "other", dataset_id: "ds-2", dataset_name: "shipping" }),
        evalRun({ id: "live", status: "running" }),
        evalRun({ id: "nothing", arms: [arm({ summary: { ...SUMMARY, pass_rate: null } })] }),
        evalRun({ id: "armless", arms: [] }),
      ],
      (run) => ({ key: run.dataset_id, name: run.dataset_name }),
      t,
      "en",
    );

    expect(lines.map((line) => [line.name, line.color])).toEqual([
      ["refunds", "var(--series-1)"],
      ["shipping", "var(--series-2)"],
    ]);
    const [refunds, shipping] = lines;
    expect(refunds?.points.map((p) => [p.index, p.tick, p.draft, p.color])).toEqual([
      [0, "trend.draftTick", true, "var(--color-success)"],
      [2, "version:7", false, "var(--color-destructive)"],
    ]);
    expect(shipping?.points.map((p) => [p.index, p.color])).toEqual([[1, "var(--series-2)"]]);
    const late = refunds?.points[1];
    expect(late?.href).toBe("/agents/agent-1/evals/late");
    expect(late?.title).toBe("sideModel:version:7|gpt-4.1");
    expect(late?.details.slice(0, 3)).toEqual([
      "trend.comparedWith:version:6",
      "trend.rate:75%",
      "trend.verdict:worse",
    ]);
    expect(late?.details).toHaveLength(4);
    expect(late?.when).toBe(late?.details[3]);
    expect(shipping?.points[0]?.details.slice(0, 2)).toEqual([
      "trend.rate:75%",
      "trend.verdict:none",
    ]);
  });
});

describe("PassRateChart", () => {
  const line = (key: string, name: string, count: number, offset = 0): PassRateLine => ({
    key,
    name,
    color: "var(--series-1)",
    points: Array.from({ length: count }, (_, i) => ({
      index: offset + i,
      rate: 0.5,
      tick: "v1",
      when: "Oct 16",
      draft: false,
      color: "var(--series-1)",
      href: "/agents/a/evals/r",
      title: "v1",
      details: [],
    })),
  });

  it("starts on the newest runs over a range to drag, and keys its lines and colours", async () => {
    render(<PassRateChart lines={[line("a", "refunds", 10), line("b", "shipping", 4, 10)]} />);

    expect(await screen.findByText("Runs shown, last 12: a×10 b×4")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Pass rate by run" })).toBeInTheDocument();
    expect(screen.getByText("refunds")).toBeInTheDocument();
    expect(screen.getByText("Breaks cases")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText(/Drag the handles under the chart/)).toBeInTheDocument();
  });

  it("names no line when there is only one", async () => {
    render(<PassRateChart lines={[line("a", "refunds", 3)]} />);
    expect(await screen.findByText("Runs shown, last 12: a×3")).toBeInTheDocument();
    expect(screen.queryByText("refunds")).toBeNull();
  });
});

describe("EvalsPanel", () => {
  it("draws the trend, then every run by dataset with its verdict", async () => {
    evalRuns.value = {
      ...evalRuns.value,
      runs: [
        evalRun({
          id: "run-3",
          dataset_id: "ds-2",
          dataset_name: "shipping",
          status: "running",
          arms: [
            arm({ source: "draft", version_number: null }),
            arm({ id: "b", role: "baseline" }),
          ],
        }),
        worse(),
        evalRun({
          id: "run-0",
          created_at: "2026-10-13T10:00:00Z",
          outcome: { ...worse().outcome!, verdict: null, baseline: null },
        }),
      ],
    };
    render(<EvalsPanel agentId="agent-1" canStart />);

    expect(screen.getByRole("group", { name: "Pass rate by run" })).toBeInTheDocument();
    expect(screen.getByText(/click it to open the run/)).toBeInTheDocument();
    expect(screen.getByText("refunds · 2 runs")).toBeInTheDocument();
    expect(screen.getByText("shipping · 1 run")).toBeInTheDocument();

    const compared = screen.getByRole("link", { name: /v7 vs v6/ });
    expect(compared).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(within(compared).getByText("Breaks 4")).toBeInTheDocument();
    expect(within(compared).getByText("gpt-4.1 75%")).toBeInTheDocument();
    expect(within(compared).getByText("claude 75%")).toBeInTheDocument();
    expect(within(compared).queryByText("Completed")).toBeNull();
    const first = screen.getByRole("link", { name: /^v7.*First result/ });
    expect(first).toHaveAttribute("href", "/agents/agent-1/evals/run-0");
    const live = screen.getByRole("link", { name: /Draft vs v7/ });
    expect(within(live).getByText("Pending")).toBeInTheDocument();
    expect(within(live).getByText("Running")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Run evals" }));
    await userEvent.click(screen.getByText("start-dialog"));
    expect(screen.queryByText("start-dialog")).not.toBeInTheDocument();
  });

  it("says one run is not yet a trend, and draws none while nothing has finished", () => {
    evalRuns.value = { ...evalRuns.value, runs: [evalRun()] };
    const { rerender } = render(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.getByText("One run so far. Run another to see a trend.")).toBeInTheDocument();

    evalRuns.value = { ...evalRuns.value, runs: [evalRun({ status: "queued" })] };
    rerender(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.queryByRole("group", { name: "Pass rate by run" })).toBeNull();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("keys each line when runs of several datasets finished", () => {
    evalRuns.value = {
      ...evalRuns.value,
      runs: [evalRun(), evalRun({ id: "run-2", dataset_id: "ds-2", dataset_name: "shipping" })],
    };
    render(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.getByText("refunds", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText("shipping", { selector: "li" })).toBeInTheDocument();
  });

  it("lists a run that has no candidate side without naming one", () => {
    evalRuns.value = { ...evalRuns.value, runs: [evalRun({ arms: [], status: "failed" })] };
    render(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.getByRole("link", { name: /Failed/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-1",
    );
  });

  it("sends an agent with no dataset to create one first", () => {
    render(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.getByText("Create a dataset first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to datasets" })).toHaveAttribute(
      "href",
      "/datasets",
    );
  });

  it("offers the first run once a dataset exists, and only to who may start one", async () => {
    datasets.items = [{ id: "ds-1" }];
    const { rerender } = render(<EvalsPanel agentId="agent-1" canStart={false} />);
    expect(screen.queryByRole("button", { name: "Run evals" })).not.toBeInTheDocument();

    rerender(<EvalsPanel agentId="agent-1" canStart />);
    expect(screen.getByText("No evals yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run evals" }));
    expect(screen.getByText("start-dialog")).toBeInTheDocument();
  });

  it("says when the runs could not be read, and retries", async () => {
    const refetch = vi.fn();
    evalRuns.value = { runs: [], isLoading: false, error: new Error("boom"), refetch };
    render(<EvalsPanel agentId="agent-1" canStart />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a placeholder while the runs load", () => {
    evalRuns.value = { ...evalRuns.value, isLoading: true };
    render(<EvalsPanel agentId="agent-1" canStart={false} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("EstimateSummary", () => {
  it("warns when the judge would grade on the model it grades", () => {
    const { unmount } = render(
      <EstimateSummary agentId="agent-1" judgeName={null} estimate={ESTIMATE} scoring={null} />,
    );
    expect(screen.queryByText(/the model being tested/)).toBeNull();
    unmount();
    render(
      <EstimateSummary
        agentId="agent-1"
        judgeName={null}
        estimate={{ ...ESTIMATE, judge_model_profile_id: "m1" }}
        scoring={null}
      />,
    );
    expect(screen.getByText(/The judge grades on gpt-4.1, the model being tested/)).toBeVisible();
  });

  it("shows each arm, the judge, the total and what the budgets keep after it", () => {
    render(
      <EstimateSummary
        agentId="agent-1"
        judgeName={null}
        estimate={ESTIMATE}
        scoring={{
          checks: { enabled: false, required: false, defaults: [] },
          trajectory: { enabled: true, required: false },
          reference: { enabled: true, required: false },
          judge: {
            enabled: true,
            agent_id: null,
            model_profile_id: null,
            scale_max: 5,
            pass_at: 4,
            criteria: [
              { name: "Policy", description: "", required: true },
              { name: "Tone", description: "", required: false },
            ],
          },
          review: { select: "none" },
        }}
      />,
    );
    expect(screen.getByText("Draft · gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText(/v6 · gpt-4.1/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /answers from the run of .*, same model/ }),
    ).toHaveAttribute("href", "/agents/agent-1/evals/run-0");
    expect(screen.getByText("Eval judge")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Graded by expected tool calls, the reference answer, and Eval judge on Policy and Tone.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("20 cases in total")).toBeInTheDocument();
    expect(screen.getByText(/can add up to \$0.60/)).toBeInTheDocument();
    expect(screen.getByText("$9.80")).toBeInTheDocument();
    expect(screen.getByText("$99.70")).toBeInTheDocument();
    expect(screen.queryByText(/more than a budget has left/)).not.toBeInTheDocument();
  });

  it("says when there is no cap, and when the run does not fit", () => {
    render(
      <EstimateSummary
        agentId="agent-1"
        scoring={null}
        judgeName="Policy judge"
        estimate={{
          ...ESTIMATE,
          arms: [
            { ...CANDIDATE_ESTIMATE, basis: "fallback" },
            { ...ESTIMATE.arms[1]!, cached_at: null },
          ],
          judge_usd: "0",
          agent_after_usd: null,
          org_after_usd: null,
          affordable: false,
        }}
      />,
    );
    expect(screen.getByText(/no history on this model/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "reused from a recent run" })).toBeInTheDocument();
    expect(screen.queryByText("Eval judge")).not.toBeInTheDocument();
    expect(screen.queryByText(/Graded by/)).not.toBeInTheDocument();
    expect(screen.getAllByText("no cap")).toHaveLength(2);
    expect(screen.getByText(/more than a budget has left/)).toBeInTheDocument();
  });
});

describe("ComparisonCard", () => {
  it("shows both sides, the changes with what confirmed means, and the efficiency axis", () => {
    render(<ComparisonCard agentId="agent-1" comparison={comparison()} tag={null} />);
    expect(screen.getByText("How the two compare")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /v7 · gpt-4.1 · dataset v3/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-1",
    );
    expect(screen.getByRole("link", { name: /Draft · gpt-4.1 · dataset v3 · not finished/ }));
    expect(screen.getByText("Compared with, an earlier run")).toBeInTheDocument();
    const confirmed = screen.getByText("Confirmed regressions");
    expect(confirmed.nextSibling).toHaveTextContent("1");
    expect(confirmed.parentElement).toHaveAttribute(
      "title",
      "Confirmed: the change held on every rerun.",
    );
    expect(screen.getByText("Unconfirmed fixes").parentElement).toHaveAttribute(
      "title",
      "Unconfirmed: on a rerun it came out one way, then the other.",
    );
    expect(screen.getByText("Cost per passed case: worse")).toBeInTheDocument();
    expect(screen.getByText(/4 cases compared, 0 answered on one side only/)).toBeInTheDocument();
  });

  it("names a baseline in the same run, and leaves out what it could not measure", () => {
    render(
      <ComparisonCard
        tag={null}
        agentId="agent-1"
        comparison={comparison({ paired: true, efficiency: null })}
      />,
    );
    expect(screen.getByText("Compared with, in the same run")).toBeInTheDocument();
    expect(screen.queryByText(/Cost per passed case/)).not.toBeInTheDocument();
  });

  it("renders nothing when there is nothing to compare with", () => {
    const { container } = render(
      <ComparisonCard
        tag={null}
        agentId="agent-1"
        comparison={comparison({ baseline: null, verdict: null })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names a proposed change by what it is", () => {
    render(
      <ComparisonCard
        tag={null}
        agentId="agent-1"
        comparison={comparison({
          candidate: { ...comparison().candidate, source: "explicit", version_number: null },
        })}
      />,
    );
    expect(screen.getByRole("link", { name: /Proposed changes · gpt-4.1/ })).toBeVisible();
  });
});

describe("ArmsTable", () => {
  it("puts every side next to the other and links a reused result to its run", () => {
    render(
      <ArmsTable
        agentId="agent-1"
        tag={null}
        live={false}
        baseline={{ ...comparison().candidate, run_id: "run-0", version_number: 6 }}
        arms={[
          arm(),
          arm({
            id: "arm-2",
            role: "baseline",
            version_number: 6,
            reused_from_arm_id: "arm-0",
            summary: { ...SUMMARY, avg_tokens: null, pass_rate: null },
          }),
        ]}
      />,
    );
    const candidate = within(screen.getByRole("row", { name: /v7 · gpt-4.1/ }));
    const baseline = within(screen.getByRole("row", { name: /v6 · gpt-4.1/ }));
    expect(candidate.getByText("120")).toBeInTheDocument();
    expect(candidate.getByText("0.5s / 1.5s")).toBeInTheDocument();
    expect(baseline.getByRole("link", { name: /result from the run of/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-0",
    );
    expect(baseline.getAllByText("—")).toHaveLength(2);
  });

  it("says a reused result was reused when its run has not finished", () => {
    render(
      <ArmsTable
        agentId="agent-1"
        tag={null}
        live
        baseline={{ ...comparison().candidate, run_id: "run-0", finished_at: null }}
        arms={[arm({ id: "arm-2", role: "baseline", reused_from_arm_id: "arm-0" })]}
      />,
    );
    expect(screen.getByRole("link", { name: "reused" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Pending" })).toBeVisible();
  });
});

describe("VerdictChip", () => {
  it("says which way a run moved as a whole when the confirmed flips can tell", () => {
    const overall = (direction: "worse" | "better") =>
      worse({ outcome: { ...worse().outcome!, overall: direction, fixed_confirmed: 1 } });
    const { unmount } = render(<VerdictChip run={overall("worse")} />);
    expect(screen.getByText("Worse overall · 4 broke, 1 fixed")).toBeInTheDocument();
    unmount();
    render(<VerdictChip run={overall("better")} />);
    expect(screen.getByText("Better overall · 4 broke, 1 fixed")).toBeInTheDocument();
  });
});

describe("CaseDetail", () => {
  it("shows each arm's answers, calls and scorer reasons side by side", () => {
    render(
      <CaseDetail
        arms={[arm(), arm({ id: "arm-2", role: "baseline", version_number: 6 })]}
        attempts={[
          attempt({
            calls: [
              { tool: "send_email", args: { to: "a@b.c" }, outcome: "blocked", reason: "writes" },
              { tool: "lookup", args: {}, outcome: "executed", reason: null },
            ],
            score: {
              results: [
                {
                  scorer: "check",
                  name: "contains 30 days",
                  required: true,
                  status: "pass",
                  score: 1,
                  reason: "found",
                  reason_code: null,
                  judge_run_id: null,
                },
                {
                  scorer: "judge",
                  name: "Tone",
                  required: true,
                  status: "pass",
                  score: 1,
                  reason: "polite",
                  reason_code: null,
                  judge_run_id: null,
                  rule: "A refusal names the policy",
                  unverified: true,
                },
              ],
            } as never,
          }),
          attempt({ id: "attempt-2", attempt: 1, outcome: false, answer: null, error: "boom" }),
          attempt({ id: "attempt-3", arm_id: "arm-2", outcome: null, agent_run_id: null }),
          attempt({
            id: "attempt-4",
            attempt: 2,
            outcome: null,
            score: caseScore({ passed: null, unscored_reason: "judge_run_failed" }),
          }),
          attempt({
            id: "attempt-5",
            attempt: 3,
            outcome: null,
            score: caseScore({ passed: null, unscored_reason: "judge_new_reason" }),
          }),
        ]}
        expectation={null}
        datasetId="ds-1"
        caseId="case-1"
      />,
    );
    expect(screen.getByText("v7 · gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText("v6 · gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText("not executed (would have written data)")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "See what the model saw" })[0]).toHaveAttribute(
      "href",
      "/runs?run=r1&view=input",
    );
    expect(screen.queryByText("What the case expects")).toBeNull();
    expect(screen.getByText('send_email({"to":"a@b.c"})')).toBeInTheDocument();
    expect(screen.getByText("contains 30 days")).toBeInTheDocument();
    expect(screen.getByText("Rerun 1")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByText("undecided")).toBeInTheDocument();
    // The judge's rule and an unverified top grade read as they do in Review.
    expect(screen.getByText("Rule: A refusal names the policy")).toBeInTheDocument();
    expect(
      screen.getByText(/Unverified: nothing quoted from the answer backs this grade/),
    ).toBeInTheDocument();
    // Not graded is not undecided: the judge failed, and says why.
    expect(screen.getByText("not graded: The judge's run did not finish.")).toBeInTheDocument();
    expect(screen.getByText("not graded: judge_new_reason")).toBeInTheDocument();
  });

  it("puts what the case expects above the answers, and the way to its dataset", () => {
    render(
      <CaseDetail
        arms={[arm()]}
        attempts={[attempt()]}
        datasetId="ds-1"
        caseId="case-1"
        expectation={{
          input: "How long do I have?",
          history: [],
          reference_answer: "30 days.",
          counter_example: "90 days.",
          expected_tool_calls: [{ tool: "lookup_policy", args: { topic: "returns" } }],
          order_mode: "in_order",
          checks: [{ type: "contains", value: "30 days" }],
          tags: [],
          note: null,
        }}
      />,
    );
    expect(screen.getByText("What the case expects")).toBeInTheDocument();
    expect(screen.getByText("30 days.")).toBeInTheDocument();
    expect(screen.getByText("90 days.")).toBeInTheDocument();
    expect(screen.getByText("Expected calls, In this order:")).toBeInTheDocument();
    expect(screen.getByText('lookup_policy({"topic":"returns"})')).toBeInTheDocument();
    expect(screen.getByText('contains {"value":"30 days"}')).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open this case in its dataset" })).toHaveAttribute(
      "href",
      "/datasets/ds-1?tab=cases&case=case-1",
    );
  });

  it("leaves out what a case does not expect", () => {
    render(
      <CaseDetail
        arms={[arm()]}
        attempts={[attempt()]}
        datasetId="ds-1"
        caseId="case-1"
        expectation={{
          input: "Hi",
          history: [],
          reference_answer: null,
          counter_example: null,
          expected_tool_calls: [],
          order_mode: "any",
          checks: [],
          tags: [],
          note: null,
        }}
      />,
    );
    expect(screen.getByText("What the case expects")).toBeInTheDocument();
    expect(screen.queryByText(/Reference/)).toBeNull();
    expect(screen.queryByText(/Expected calls/)).toBeNull();
    expect(screen.queryByText("Checks:")).toBeNull();
  });
});
