import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { comparison, FLIP } from "@/test-utils/eval-runs";
import type { EvalComparison } from "@/types/eval-runs";
import { ResultEvidence } from "./result-evidence";

const state = vi.hoisted(() => ({
  comparison: undefined as EvalComparison | undefined,
  error: null as Error | null,
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalComparison: () => ({ ...state, refetch: state.retry }),
}));
vi.mock("./changed-answers", () => ({
  ChangedAnswers: ({ flips, preview }: { flips: EvalComparison["cases"]; preview: boolean }) => (
    <ul aria-label={preview ? "Answer previews" : "Answers"}>
      {flips.map((flip) => (
        <li key={flip.case_id}>{flip.case_id}</li>
      ))}
    </ul>
  ),
}));
beforeEach(() => {
  state.comparison = undefined;
  state.error = null;
  vi.clearAllMocks();
});

it("shows loading and a recoverable error instead of an empty success", async () => {
  const view = render(<ResultEvidence agentId="a1" runId="r1" />);
  expect(screen.getByRole("status")).toBeVisible();
  state.error = new Error("Cannot read answers");
  view.rerender(<ResultEvidence agentId="a1" runId="r1" />);
  expect(screen.getByText("Cannot read answers")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.retry).toHaveBeenCalledOnce();
});

it("prioritizes regressions, leaves uncertainty to the answer renderer and previews the first answer", () => {
  state.comparison = comparison({
    cases: [
      { ...FLIP, case_id: "fixed", flip: "fixed", confirmed: false },
      { ...FLIP, case_id: "same", flip: "unchanged" },
      { ...FLIP, case_id: "broken" },
      { ...FLIP, case_id: "incomplete", flip: "incomplete" },
    ],
  });
  render(<ResultEvidence agentId="a1" runId="r1" />);
  expect(screen.getByRole("list", { name: "Answer previews" })).toBeVisible();
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "broken",
    "fixed",
  ]);
});

it.each([
  comparison({ verdict: "invalid" }),
  comparison({ baseline: null }),
  comparison({ cases: [] }),
])("keeps the full test reachable when changed-answer evidence cannot be shown", (value) => {
  state.comparison = value;
  render(<ResultEvidence agentId="a1" runId="r1" />);
  expect(screen.queryByRole("list")).toBeNull();
  expect(screen.getByRole("link", { name: "Open the full check" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/r1",
  );
  expect(
    screen.getByText(
      value.verdict === "invalid" ? /could not reliably compare/ : /no changed answers/,
    ),
  ).toBeVisible();
});
