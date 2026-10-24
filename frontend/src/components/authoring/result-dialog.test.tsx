import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { authoringRequest, batch, hunk } from "@/test-utils/authoring";
import { arm, evalRun } from "@/test-utils/eval-runs";
import {
  AuthoringResultDialog,
  AuthoringResultNotice,
  ChangePreview,
  CheckedAnswers,
} from "./result-dialog";
import { TextDiff } from "./text-diff";

const reads = vi.hoisted(() => ({
  runState: "completed",
  caseState: "completed",
  total: 1,
  noAnswers: false,
  retryRun: vi.fn(),
  retryCases: vi.fn(),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({
    run:
      reads.runState === "loading"
        ? null
        : evalRun({
            agent_id: "agent-1",
            status: reads.runState === "running" ? "running" : "completed",
            arms: [
              arm({ id: "base", role: "baseline" }),
              arm({ id: "candidate", role: "candidate" }),
            ],
          }),
    error: reads.runState === "error" ? new Error("offline") : null,
    refetch: reads.retryRun,
  }),
  useEvalCases: () => ({
    cases: [
      {
        case_id: "case-1",
        input: "When can I return shoes?",
        attempts: reads.noAnswers
          ? []
          : [
              { arm_id: "base", attempt: 0, answer: "90 days" },
              { arm_id: "candidate", attempt: 0, answer: "30 days" },
            ],
      },
    ],
    total: reads.total,
    isLoading: reads.caseState === "loading",
    error: reads.caseState === "error" ? new Error("offline") : null,
    refetch: reads.retryCases,
  }),
}));
beforeEach(() => {
  reads.runState = "completed";
  reads.caseState = "completed";
  reads.total = 1;
  reads.noAnswers = false;
  vi.clearAllMocks();
});

describe("AuthoringResultDialog", () => {
  it("opens after an observed request finishes and stays closed after dismissal", async () => {
    const running = authoringRequest({
      status: "running",
      evidence: { runs: 8, problem_answers: 3 },
    });
    const { rerender } = render(
      <AuthoringResultNotice request={running} batch={null} canReadRuns />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    rerender(
      <AuthoringResultNotice
        request={{ ...running, status: "completed" }}
        batch={batch()}
        canReadRuns
      />,
    );
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Suggested improvements");
    expect(screen.getByText("3 problem answers found in the source evidence")).toBeInTheDocument();
    expect(screen.getByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();
    expect(screen.getByText("Readers corrected the refund window.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to the agent" }));
    rerender(
      <AuthoringResultNotice
        request={{ ...running, status: "completed" }}
        batch={batch()}
        canReadRuns
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review result" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("explains an empty result with dropped reasons and no expected effect", () => {
    render(
      <AuthoringResultDialog
        request={authoringRequest({
          report: {
            proposed: 1,
            recorded: 0,
            rejected: [
              {
                kind: "instructions",
                reason: "unanchored",
                change: { old_text: "Missing passage", new_text: "New passage" },
              },
            ],
          },
        })}
        batch={batch({ hunks: [], expected_effect: "Invented improvement" })}
        canReadRuns={false}
        onOpenChange={vi.fn()}
      />,
    );
    expect(screen.getByText("The assistant found nothing it could apply.")).toBeInTheDocument();
    expect(screen.getByText("Missing passage")).toBeInTheDocument();
    expect(screen.queryByText("Invented improvement")).not.toBeInTheDocument();
  });

  it("shows answers from both check arms only to a reader of runs", () => {
    const props = {
      request: authoringRequest(),
      batch: batch({ check_eval_run_ids: ["eval-1"] }),
      onOpenChange: vi.fn(),
    };
    const { rerender } = render(<AuthoringResultDialog {...props} canReadRuns />);
    expect(screen.getByText("When can I return shoes?")).toBeInTheDocument();
    expect(screen.getByText("90 days")).toBeInTheDocument();
    expect(screen.getByText("30 days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the full check" })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/eval-1",
    );
    rerender(<AuthoringResultDialog {...props} canReadRuns={false} />);
    expect(screen.queryByText("When can I return shoes?")).not.toBeInTheDocument();
    expect(screen.queryByText("You said 90 days")).not.toBeInTheDocument();
  });

  it("keeps a heading in its own context row even when the stored boundary has no newline", () => {
    render(
      <TextDiff
        context="## How to answer"
        before="Lead with the answer."
        after="Ask for the receipt."
        trailing="Then stop."
      />,
    );
    const heading = screen.getByText("## How to answer").closest("tr")!;
    expect(within(heading).queryByText("Lead with the answer.")).not.toBeInTheDocument();
    expect(screen.getByText("Lead with the answer.").closest("tr")).not.toBe(heading);
  });
});

it("shows loading, live and unavailable checks without pretending an answer exists", () => {
  reads.runState = "loading";
  const { rerender } = render(<CheckedAnswers runId="check" />);
  expect(screen.getByRole("status")).toHaveTextContent("Reading the checked answers");
  reads.runState = "error";
  rerender(<CheckedAnswers runId="check" />);
  expect(screen.getByRole("alert")).toHaveTextContent("could not be read");
  reads.runState = "running";
  rerender(<CheckedAnswers runId="check" />);
  expect(screen.getByText("Run a check to see how it would answer.")).toBeInTheDocument();
  reads.runState = "completed";
  reads.caseState = "loading";
  rerender(<CheckedAnswers runId="check" />);
  expect(screen.getByRole("status")).toHaveTextContent("Reading the checked answers");
  reads.caseState = "error";
  rerender(<CheckedAnswers runId="check" />);
  expect(screen.getByRole("alert")).toHaveTextContent("could not be read");
  reads.caseState = "completed";
  reads.noAnswers = true;
  reads.total = 2;
  rerender(<CheckedAnswers runId="check" />);
  expect(screen.getAllByText("No answer was recorded.")).toHaveLength(2);
  expect(screen.getByText("1 more question in the full check")).toBeInTheDocument();
});

it("can observe a newly running request and never shows an older request's changes", () => {
  const request = authoringRequest();
  const props = { batch: batch({ request_id: "older-request" }), canReadRuns: false };
  const { rerender } = render(<AuthoringResultNotice request={request} {...props} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  rerender(<AuthoringResultNotice request={{ ...request, status: "running" }} {...props} />);
  rerender(<AuthoringResultNotice request={request} {...props} />);
  expect(screen.getByText("The assistant found nothing it could apply.")).toBeInTheDocument();
  expect(screen.getByText(/Try adding rated answers/)).toBeInTheDocument();
  expect(screen.queryByText("Readers corrected the refund window.")).not.toBeInTheDocument();
});

it("previews field changes and tool renames without editable controls", () => {
  const { rerender } = render(
    <ChangePreview
      hunk={hunk({
        kind: "spec_field",
        op: "set",
        path: "model_settings/temperature",
        base_value: 0.1,
        new_value: 0.2,
      })}
    />,
  );
  expect(screen.getByText("0.1")).toBeInTheDocument();
  expect(screen.getByText("0.2")).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  rerender(
    <ChangePreview
      hunk={hunk({
        kind: "tool_override",
        tool_id: "lookup",
        base_name: "Old name",
        new_name: "New name",
        base_description: "Old description",
        new_description: "New description",
        applies: false,
      })}
    />,
  );
  expect(screen.getByText(/Old name/)).toHaveTextContent("Old description");
  expect(screen.getByText(/New name/)).toHaveTextContent("New description");
});

it("replaces raw identities in the result dialog's effect with the source count", () => {
  const id = "467abd40-2539-49d3-b239-2c960f7b7b07";
  render(
    <AuthoringResultDialog
      request={authoringRequest()}
      canReadRuns={false}
      onOpenChange={vi.fn()}
      batch={batch({
        expected_effect: `Improve ${id}`,
        hunks: [hunk({ evidence: [{ run_id: id, quote: "Wrong" }] })],
      })}
    />,
  );
  expect(screen.getByText(/Proposed to address problems in 1 source answer/)).toBeInTheDocument();
  expect(screen.queryByText(`Improve ${id}`)).not.toBeInTheDocument();
});

it("handles older proposals whose tool names and passages are absent", () => {
  const { rerender } = render(
    <AuthoringResultDialog
      request={authoringRequest({ evidence: {} })}
      batch={batch({ hunks: [hunk({ old_text: "", new_text: "" })] })}
      canReadRuns={false}
      onOpenChange={vi.fn()}
    />,
  );
  expect(screen.getAllByText("No text")).toHaveLength(2);
  rerender(
    <ChangePreview
      hunk={hunk({
        kind: "tool_override",
        tool_id: null,
        base_name: null,
        new_name: null,
        base_description: null,
        new_description: null,
      })}
    />,
  );
  expect(screen.getAllByText("No text")).toHaveLength(2);
  rerender(
    <ChangePreview
      hunk={hunk({
        kind: "tool_override",
        tool_id: "lookup",
        base_name: "Lookup",
        new_name: null,
        base_description: "Read the order",
        new_description: null,
      })}
    />,
  );
  expect(screen.getAllByText(/Read the order/)).toHaveLength(2);
});
