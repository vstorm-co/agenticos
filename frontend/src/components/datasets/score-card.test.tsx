import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { caseScore } from "@/test-utils/scores";

import type { CaseScore, ScorerResult } from "@/types/scoring";
import { ScoreCard } from "./score-card";

function result(overrides: Partial<ScorerResult> = {}): ScorerResult {
  return {
    scorer: "judge",
    name: "tone",
    required: true,
    status: "fail",
    score: 0.4,
    reason: "2/5: curt",
    reason_code: null,
    unverified_quotes: [],
    judge_run_id: null,
    ...overrides,
  };
}

function score(overrides: Partial<CaseScore> = {}): CaseScore {
  return {
    ...caseScore(),
    id: "s1",
    dataset_id: "d1",
    case_id: "c1",
    case_revision_id: "r1",
    question: "How long is the refund window?",
    reference_answer: null,
    run_id: "run-1",
    run_model: null,
    judge: null,
    results: [result()],
    passed: false,
    review_state: "none",
    human_passed: null,
    human_note: null,
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_by_user_id: null,
    created_at: "2026-10-13T00:00:00Z",
    outcome: false,
    ...overrides,
  };
}

/**
 * One score: each scorer's verdict and reason, and a person's verdict apart from
 * them - so the judge's opinion stays readable after it is overruled.
 */
describe("ScoreCard", () => {
  it("says which agent answered, at which version, on which model, and when", () => {
    const { rerender } = render(
      <ScoreCard
        score={score({ run_model: "gpt-4.1", agent_name: "Support", agent_version: 3 })}
      />,
    );

    expect(screen.getByText("Support v3")).toBeInTheDocument();
    expect(screen.getByText("gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toHaveAttribute("datetime", "2026-10-13T00:00:00Z");

    rerender(<ScoreCard score={score({ agent_name: "Support", agent_version: null })} />);
    expect(screen.getByText("Support")).toBeInTheDocument();
  });

  it("shows what the case expected: the tool calls in their order, and the checks", () => {
    render(
      <ScoreCard
        score={score({
          expected_tool_calls: [
            { tool: "search_kb", args: { query: "refunds" } },
            { tool: "lookup_order", args: {} },
          ],
          order_mode: "in_order",
          checks: [{ type: "contains", value: "days" }],
        })}
      />,
    );

    expect(screen.getByText("Expected tool calls, in this order")).toBeInTheDocument();
    expect(screen.getByText('search_kb {"query":"refunds"}')).toBeInTheDocument();
    expect(screen.getByText("lookup_order")).toBeInTheDocument();
    expect(screen.getByText("contains days")).toBeInTheDocument();
  });

  it("folds a long answer and opens it on request, and says when none is kept", async () => {
    const long = `${"word ".repeat(100)}end`;
    const { rerender } = render(<ScoreCard score={score({ answer: long })} />);

    const toggle = screen.getByRole("button", { name: "Show all" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    rerender(<ScoreCard score={score({ answer: "Thirty days." })} />);
    expect(screen.getByText("Thirty days.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all" })).toBeNull();

    rerender(<ScoreCard score={score({ answer: null })} />);
    expect(screen.getByText("The answer is not kept.")).toBeInTheDocument();
  });

  it("marks the judge's quotes the answer does not hold apart from its reason", () => {
    render(
      <ScoreCard
        score={score({ results: [result({ unverified_quotes: ["ninety days", "a refund"] })] })}
      />,
    );

    expect(screen.getByText("2/5: curt")).toBeInTheDocument();
    expect(
      screen.getByText("Quoted, but not in the answer: ninety days · a refund"),
    ).toBeInTheDocument();
  });

  it("shows what the scored revision asked, and its reference answer", () => {
    render(<ScoreCard score={score({ reference_answer: "Thirty days." })} />);

    expect(screen.getByText("How long is the refund window?")).toBeInTheDocument();
    expect(screen.getByText("Thirty days.")).toBeInTheDocument();
  });

  it("shows what did not pass first, folds what passed, and links the scored run", async () => {
    render(
      <ScoreCard
        score={score({
          results: [
            result({ judge_run_id: "judge-1" }),
            result({
              scorer: "check",
              name: "contains 'days'",
              status: "pass",
              reason: "Contains it",
              required: false,
            }),
          ],
        })}
      />,
    );

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("2/5: curt")).toBeInTheDocument();
    expect(screen.queryByText("Contains it")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "+1 passed" }));
    expect(screen.getByText("Contains it")).toBeInTheDocument();
    expect(screen.getByText("optional")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Judge's run" })).toHaveAttribute(
      "href",
      "/runs?run=judge-1",
    );
    expect(screen.getByRole("link", { name: "Scored run" })).toHaveAttribute(
      "href",
      "/runs?run=run-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Hide what passed" }));
    expect(screen.queryByText("Contains it")).toBeNull();
  });

  it("links the question to its case with the case's tags, and an eval run's score to the run", () => {
    render(
      <ScoreCard
        score={score({
          case_tags: ["billing"],
          eval_run_id: "e1",
          agent_id: "a1",
          results: [result({ status: "pass" })],
        })}
      />,
    );

    expect(screen.getByRole("link", { name: "How long is the refund window?" })).toHaveAttribute(
      "href",
      "/datasets/d1?tab=cases&case=c1",
    );
    expect(screen.getByText("billing")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Eval run ↗" })).toHaveAttribute(
      "href",
      "/agents/a1/evals/e1",
    );
    expect(screen.queryByRole("link", { name: "Scored run" })).toBeNull();
    expect(screen.getByText("2/5: curt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /passed/ })).toBeNull();
  });

  it("says why the judge did not run in the reader's words", () => {
    render(
      <ScoreCard
        score={score({
          outcome: null,
          passed: null,
          run_id: null,
          results: [result({ status: "skipped", reason_code: "ai_assistance_off", reason: "raw" })],
        })}
      />,
    );

    expect(screen.getAllByText("Not graded")).toHaveLength(2);
    expect(
      screen.getByText(
        "AI assistance is switched off for this organization, so the judge did not run.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("raw")).toBeNull();
    expect(screen.queryByRole("link", { name: "Scored run" })).toBeNull();
  });

  it("marks a person's verdict apart from the scorers, with their note", () => {
    render(
      <ScoreCard
        score={score({
          outcome: true,
          human_passed: true,
          human_note: "Policy changed",
          review_state: "done",
        })}
      />,
    );

    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Decided in review")).toBeInTheDocument();
    expect(screen.getByText("Policy changed")).toBeInTheDocument();
    expect(screen.getByText("Fail")).toBeInTheDocument();
  });

  it("records a verdict with the note written beside it", async () => {
    const onVerdict = vi.fn();
    render(<ScoreCard score={score()} onVerdict={onVerdict} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "Fine by policy");
    await userEvent.click(screen.getByRole("button", { name: "Mark passed" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));

    expect(onVerdict).toHaveBeenNthCalledWith(1, { passed: true, note: "Fine by policy" });
    expect(onVerdict).toHaveBeenNthCalledWith(2, { passed: false, note: "Fine by policy" });
  });

  it("sends no note when none was written, and withdraws without one", async () => {
    const onVerdict = vi.fn();
    render(
      <ScoreCard score={score({ human_passed: false, human_note: "x" })} onVerdict={onVerdict} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Withdraw decision" }));
    await userEvent.clear(screen.getByRole("textbox", { name: "Note" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));

    expect(onVerdict).toHaveBeenNthCalledWith(1, { passed: null, note: null });
    expect(onVerdict).toHaveBeenNthCalledWith(2, { passed: false, note: null });
  });

  it("holds the decision while one is being saved", () => {
    render(<ScoreCard score={score()} onVerdict={vi.fn()} busy />);

    expect(screen.getByRole("button", { name: "Mark passed" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mark failed" })).toBeDisabled();
  });

  it("offers review only for a score not already waiting", async () => {
    const onReview = vi.fn();
    const { rerender } = render(<ScoreCard score={score()} onReview={onReview} />);

    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));
    expect(onReview).toHaveBeenCalled();

    rerender(<ScoreCard score={score({ review_state: "pending" })} onReview={onReview} busy />);
    expect(screen.getByText("Waiting for a decision")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to review" })).toBeNull();
  });
});
