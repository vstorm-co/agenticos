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
import { ArmsTable } from "./arms-table";
import { CaseDetail } from "./case-detail";
import { ComparisonCard } from "./comparison-card";
import { EstimateSummary } from "./estimate-summary";
import { EvalStatusBadge } from "./eval-status-badge";
import { EvalsPanel, candidateLabel } from "./evals-panel";
import { percent, seconds, usd } from "./format";

const evalRuns = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
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

describe("candidateLabel", () => {
  const t = (key: string, values?: { version: number }) =>
    values ? `${key}:${values.version}` : key;

  it("names a version by its number, a draft and a proposal by what they are", () => {
    expect(candidateLabel(evalRun(), t)).toBe("version:7");
    expect(
      candidateLabel(evalRun({ arms: [arm({ source: "draft", version_number: null })] }), t),
    ).toBe("draft");
    expect(
      candidateLabel(evalRun({ arms: [arm({ source: "explicit", version_number: null })] }), t),
    ).toBe("proposed");
    expect(candidateLabel(evalRun({ arms: [] }), t)).toBe("draft");
  });
});

describe("EvalsPanel", () => {
  it("lists the runs with each candidate's pass rate, cost and status", async () => {
    evalRuns.value = {
      ...evalRuns.value,
      runs: [evalRun({ arms: [arm(), arm({ id: "arm-2", model_label: "claude" })] })],
    };
    render(<EvalsPanel agentId="agent-1" canStart canRunDraft currentVersion={7} />);

    const row = screen.getByRole("link", { name: /refunds v3 · v7/ });
    expect(row).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(within(row).getAllByText("75%")).toHaveLength(2);
    expect(within(row).getByText(/gpt-4.1, claude/)).toBeInTheDocument();
    expect(within(row).getByText("Completed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Run evals" }));
    await userEvent.click(screen.getByText("start-dialog"));
    expect(screen.queryByText("start-dialog")).not.toBeInTheDocument();
  });

  it("sends an agent with no dataset to create one first", () => {
    render(<EvalsPanel agentId="agent-1" canStart canRunDraft currentVersion={7} />);
    expect(screen.getByText("Create a dataset first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to datasets" })).toHaveAttribute(
      "href",
      "/datasets",
    );
  });

  it("offers the first run once a dataset exists, and only to who may start one", async () => {
    datasets.items = [{ id: "ds-1" }];
    const { rerender } = render(
      <EvalsPanel agentId="agent-1" canStart canRunDraft={false} currentVersion={null} />,
    );
    // Nothing published and no edit access: there is nothing this caller may run.
    expect(screen.queryByRole("button", { name: "Run evals" })).not.toBeInTheDocument();

    rerender(<EvalsPanel agentId="agent-1" canStart canRunDraft currentVersion={null} />);
    expect(screen.getByText("No evals yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run evals" }));
    expect(screen.getByText("start-dialog")).toBeInTheDocument();
  });

  it("says when the runs could not be read, and retries", async () => {
    const refetch = vi.fn();
    evalRuns.value = { runs: [], isLoading: false, error: new Error("boom"), refetch };
    render(<EvalsPanel agentId="agent-1" canStart canRunDraft currentVersion={7} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a placeholder while the runs load", () => {
    evalRuns.value = { ...evalRuns.value, isLoading: true };
    render(<EvalsPanel agentId="agent-1" canStart={false} canRunDraft currentVersion={7} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("EstimateSummary", () => {
  it("shows each arm, the judge, the total and what the budgets keep after it", () => {
    render(
      <EstimateSummary
        agentId="agent-1"
        estimate={ESTIMATE}
        scoring={{
          checks: { enabled: false, required: false, defaults: [] },
          trajectory: { enabled: true, required: false },
          reference: { enabled: true, required: false },
          judge: {
            enabled: true,
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
    expect(screen.getByRole("link", { name: "reused from a recent run" })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-0",
    );
    expect(screen.getByText("Eval judge")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Graded by expected tool calls, the reference answer, and the Eval judge on Policy and Tone.",
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
        estimate={{
          ...ESTIMATE,
          arms: [{ ...CANDIDATE_ESTIMATE, basis: "fallback" }],
          judge_usd: "0",
          agent_after_usd: null,
          org_after_usd: null,
          affordable: false,
        }}
      />,
    );
    expect(screen.getByText(/no history on this model/)).toBeInTheDocument();
    expect(screen.queryByText("Eval judge")).not.toBeInTheDocument();
    expect(screen.queryByText(/Graded by/)).not.toBeInTheDocument();
    expect(screen.getAllByText("no cap")).toHaveLength(2);
    expect(screen.getByText(/more than a budget has left/)).toBeInTheDocument();
  });
});

describe("ComparisonCard", () => {
  it("shows the verdict, both sides, the flips and the efficiency axis", () => {
    render(<ComparisonCard agentId="agent-1" comparison={comparison()} tag={null} />);
    expect(screen.getByText("Sample too small")).toBeInTheDocument();
    expect(screen.getByText(/too few to tell the two apart/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /v7 · gpt-4.1 · dataset v3/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-1",
    );
    expect(screen.getByRole("link", { name: /Draft · gpt-4.1 · dataset v3 · not finished/ }));
    expect(screen.getByText("Baseline, an earlier run")).toBeInTheDocument();
    expect(screen.getByText("Confirmed regressions").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Cost per passed case: worse")).toBeInTheDocument();
    expect(screen.getByText(/4 cases compared, 0 answered on one side only/)).toBeInTheDocument();
  });

  it("names a baseline in the same run, and why a comparison is refused", () => {
    render(
      <ComparisonCard
        tag={null}
        agentId="agent-1"
        comparison={comparison({
          paired: true,
          verdict: "invalid",
          invalid_reason: "The two sides were graded by a different judge, model or rubric.",
          efficiency: null,
        })}
      />,
    );
    expect(screen.getByText("Not comparable")).toBeInTheDocument();
    expect(screen.getByText(/graded by a different judge/)).toBeInTheDocument();
    expect(screen.getByText("Baseline, in the same run")).toBeInTheDocument();
    expect(screen.queryByText(/Cost per passed case/)).not.toBeInTheDocument();
  });

  it("says there is nothing to compare with yet", () => {
    render(
      <ComparisonCard
        tag={null}
        agentId="agent-1"
        comparison={comparison({ baseline: null, verdict: null })}
      />,
    );
    expect(screen.getByText(/no earlier run of this dataset/)).toBeInTheDocument();
    expect(screen.queryByText("Confirmed regressions")).not.toBeInTheDocument();
  });

  it("explains a verdict that carries no reason of its own", () => {
    render(
      <ComparisonCard agentId="agent-1" comparison={comparison({ verdict: null })} tag={null} />,
    );
    expect(screen.getByText(/No case flipped and held/)).toBeInTheDocument();
  });
});

describe("ArmsTable", () => {
  it("puts every arm's axes side by side and marks a reused baseline", () => {
    render(
      <ArmsTable
        tag={null}
        arms={[
          arm(),
          arm({
            id: "arm-2",
            role: "baseline",
            reused_from_arm_id: "arm-0",
            summary: { ...SUMMARY, avg_tokens: null, pass_rate: null },
          }),
        ]}
      />,
    );
    const candidate = within(screen.getByRole("row", { name: /Candidate on/ }));
    const baseline = within(screen.getByRole("row", { name: /Baseline on/ }));
    expect(candidate.getByText("120")).toBeInTheDocument();
    expect(candidate.getByText("0.5s / 1.5s")).toBeInTheDocument();
    expect(baseline.getByText(/reused/)).toBeInTheDocument();
    expect(baseline.getAllByText("—")).toHaveLength(2);
  });
});

describe("CaseDetail", () => {
  it("shows each arm's answers, calls and scorer reasons side by side", () => {
    render(
      <CaseDetail
        arms={[arm(), arm({ id: "arm-2", role: "baseline" })]}
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
              ],
            } as never,
          }),
          attempt({ id: "attempt-2", attempt: 1, outcome: false, answer: null, error: "boom" }),
          attempt({ id: "attempt-3", arm_id: "arm-2", outcome: null }),
        ]}
      />,
    );
    expect(screen.getByText("Candidate on gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText("Baseline on gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText("held, writes")).toBeInTheDocument();
    expect(screen.getByText('send_email({"to":"a@b.c"})')).toBeInTheDocument();
    expect(screen.getByText("contains 30 days")).toBeInTheDocument();
    expect(screen.getByText("Rerun 1")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByText("undecided")).toBeInTheDocument();
  });
});
