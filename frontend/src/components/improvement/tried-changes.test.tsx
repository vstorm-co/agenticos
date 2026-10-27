import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { hunk } from "@/test-utils/authoring";
import { SESSION } from "@/test-utils/improvement";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { TriedChanges } from "./tried-changes";

const state = vi.hoisted(() => ({
  changes: {} as Record<number, Hunk[]>,
  evidence: [] as {
    run_id: string;
    conversation_id: string | null;
    kind: string;
    question: string;
  }[],
  isLoading: false,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useAttemptChanges: (_agent: string, _run: string, attempt: number) => ({
    changes: state.changes[attempt] ?? [],
    isLoading: state.isLoading,
    error: state.error,
  }),
  useImprovementEvidence: () => ({ evidence: { items: state.evidence } }),
}));

const FIRST = SESSION.iterations[0]!;
const AFTER_REGRESSION: Improvement = {
  ...SESSION,
  status: "stopped",
  stop_reason: "regression",
  iterations: [
    {
      ...FIRST,
      id: "r1",
      number: 1,
      batch_id: "b1",
      verdict: "no_change",
      included_hunk_ids: null,
    },
    {
      ...FIRST,
      id: "r2",
      number: 2,
      batch_id: "b2",
      verdict: "regression",
      included_hunk_ids: ["h1"],
    },
  ],
};

beforeEach(() => {
  state.changes = {
    1: [hunk({ id: "h0", new_text: "Answer in one line." })],
    2: [
      hunk({ id: "h1", edited_text: "Refunds take 30 days." }),
      hunk({ id: "h2", kind: "spec_field" }),
    ],
  };
  state.isLoading = false;
  state.error = null;
  state.evidence = [];
});

it("names the test question an earlier attempt's change quotes, with what it asked", () => {
  state.evidence = [
    { run_id: "q1", conversation_id: null, kind: "train_eval", question: "Is delivery free?" },
  ];
  state.changes = {
    1: [
      hunk({
        id: "h0",
        evidence: [{ run_id: "q1", quote: "Delivery is free", source: "test_question", number: 1 }],
      }),
    ],
    2: [],
  };
  render(<TriedChanges session={AFTER_REGRESSION} />);
  expect(screen.getByText("Delivery is free")).toBeInTheDocument();
  expect(screen.getByText("Test question 1")).toBeInTheDocument();
  expect(screen.getByText(/Is delivery free\?/)).toBeInTheDocument();
});

it("shows what the latest attempt tested and what its check came to, the earlier one folded", () => {
  render(<TriedChanges session={AFTER_REGRESSION} />);
  const latest = screen.getByText("Attempt 2: the changes broke questions that worked.");
  expect(latest.closest("details")).toHaveAttribute("open");
  const earlier = screen.getByText("Attempt 1: no measurable change.");
  expect(earlier.closest("details")).not.toHaveAttribute("open");
  expect(screen.getAllByText("Tested in attempt 2")).toHaveLength(1);
  expect(screen.getByText("Not tested")).toBeInTheDocument();
  expect(screen.getByText("Reworded by you")).toBeInTheDocument();
  expect(
    screen.getByText("The reason describes the proposed wording, before you changed it."),
  ).toBeInTheDocument();
  expect(latest.closest("details")).toHaveTextContent("Refunds take 30 days.");
  expect(screen.getByText("Tested in attempt 1")).toBeInTheDocument();
});

it("names an attempt held back rather than tried, and one that proposed nothing", () => {
  render(
    <TriedChanges
      session={{
        ...AFTER_REGRESSION,
        iterations: [
          { ...FIRST, id: "r1", number: 1, batch_id: null, verdict: null },
          { ...FIRST, id: "r2", number: 2, batch_id: "b2", verdict: null },
          { ...FIRST, id: "r4", number: 4, batch_id: "b4", verdict: null },
        ],
      }}
    />,
  );
  expect(screen.getByText("Changes held back for another attempt, not tested")).toBeInTheDocument();
  expect(screen.getByText("Attempt 1: no change was proposed.")).toBeInTheDocument();
  expect(screen.getByText("Attempt 2: changes proposed, not tested yet.")).toBeInTheDocument();
});

it("says it is loading, why it could not read an attempt's changes, and when it wrote none", () => {
  const session = { ...AFTER_REGRESSION, iterations: [AFTER_REGRESSION.iterations[1]!] };
  state.isLoading = true;
  const view = render(<TriedChanges session={session} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading the changes…");
  state.isLoading = false;
  state.error = new Error("Changes unavailable");
  view.rerender(<TriedChanges session={session} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Changes unavailable");
  state.error = null;
  state.changes = {};
  view.rerender(<TriedChanges session={session} />);
  expect(screen.getByText("No change was written in this attempt.")).toBeInTheDocument();
});
