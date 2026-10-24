import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { authoringRequest, batch } from "@/test-utils/authoring";
import { arm, evalRun } from "@/test-utils/eval-runs";
import { AuthoringResultDialog, AuthoringResultNotice } from "./result-dialog";
import { TextDiff } from "./text-diff";

vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({
    run: evalRun({
      agent_id: "agent-1",
      status: "completed",
      arms: [arm({ id: "base", role: "baseline" }), arm({ id: "candidate", role: "candidate" })],
    }),
    error: null,
  }),
  useEvalCases: () => ({
    cases: [
      {
        case_id: "case-1",
        input: "When can I return shoes?",
        attempts: [
          { arm_id: "base", attempt: 0, answer: "90 days" },
          { arm_id: "candidate", attempt: 0, answer: "30 days" },
        ],
      },
    ],
    total: 1,
    isLoading: false,
    error: null,
  }),
}));

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
