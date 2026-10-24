import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Improvement, KnowledgeCheckEstimate } from "@/types/improvement";
import { KnowledgeDrafts } from "./knowledge-drafts";
const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  check: vi.fn(),
  topics: true,
  runStatus: "completed",
  invalidated: false,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    estimateKnowledge: { mutateAsync: state.estimate, isPending: false },
    checkKnowledge: { mutateAsync: state.check, isPending: false },
  }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({
    topics: state.topics ? [{ id: "t1", has_draft: true, can_edit: true, label: "Returns" }] : [],
  }),
  useKnowledgeGap: () => ({
    topic: { draft: { title: "Return policy", content: "Returns take 30 days.", sources: [] } },
  }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasetCases: () => ({
    cases: [
      { case_id: "q1", input: "Return window?", improvement_partition: "holdout" },
      { case_id: "q2", input: "Learning example", improvement_partition: "train" },
    ],
    total: 2,
  }),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({
    run: {
      status: state.runStatus,
      proposal_check: { knowledge: { supported: false, invalidated: state.invalidated } },
    },
  }),
  useEvalComparison: () => ({
    comparison: { verdict: "better", fixed_confirmed: 2, regressions_confirmed: 0 },
  }),
}));
vi.mock("@/components/knowledge-gaps/knowledge-gap-dialog", () => ({
  KnowledgeGapDialog: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog">
      <button onClick={onClose}>Close review</button>
    </div>
  ),
}));
const SESSION: Improvement = {
  id: "s1",
  agent_id: "a1",
  created_by_user_id: "u1",
  improver_agent_id: null,
  status: "ready",
  stage: "judging",
  iteration: 1,
  max_iterations: 3,
  base_version_id: "v1",
  dataset_id: "d1",
  dataset_version: 1,
  suite_id: null,
  estimate_usd: "0.1",
  budget_usd: "1",
  spent_usd: "0.03",
  best_iteration_id: "r1",
  stop_reason: null,
  error: null,
  created_at: "2026-10-24T12:00:00Z",
  finished_at: null,
  timeline: [],
  iterations: [
    {
      id: "r1",
      number: 1,
      authoring_request_id: "p1",
      batch_id: "b1",
      eval_run_ids: [],
      candidate_spec_hash: "hash",
      attribution_eval_run_ids: {},
      dropped_hunk_ids: [],
      dropped: [],
      verdict: "better",
      verdict_detail: { fixed: 3, broken: 0 },
      cost_usd: "0.03",
      started_at: "2026-10-24T12:00:00Z",
      ended_at: null,
    },
  ],
};
const QUOTE: KnowledgeCheckEstimate = {
  total_usd: "0.02",
  affordable: true,
  can_measure: true,
  cases: 5,
  excluded: 2,
  supported: false,
  draft_hash: "a".repeat(64),
  reason: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  state.topics = true;
  state.runStatus = "completed";
  state.invalidated = false;
  state.estimate.mockResolvedValue(QUOTE);
  state.check.mockResolvedValue({ id: "k1" });
});
async function choose() {
  await userEvent.selectOptions(screen.getByRole("combobox"), "t1");
  await userEvent.click(screen.getByLabelText("Return window?"));
}
it("requires a separately priced confirmation and keeps fact verification visible", async () => {
  render(<KnowledgeDrafts session={SESSION} />);
  expect(screen.getByLabelText("Learning example")).toBeDisabled();
  await choose();
  expect(screen.getByText(/Unsupported — verify the facts/)).toBeInTheDocument();
  expect(screen.getByText(/Assuming search finds this passage/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(await screen.findByText(/5 independent questions/)).toHaveTextContent(/2 excluded/);
  expect(state.check).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm and check the draft" }));
  expect(state.check).toHaveBeenCalledWith({
    topic_id: "t1",
    round: 1,
    case_ids: ["q1"],
    confirmed: true,
    draft_hash: QUOTE.draft_hash,
    estimate_usd: "0.02",
  });
});
it("invalidates the quote when selected questions change", async () => {
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  await screen.findByText(/5 independent questions/);
  await userEvent.click(screen.getByLabelText("Return window?"));
  expect(
    screen.queryByRole("button", { name: "Confirm and check the draft" }),
  ).not.toBeInTheDocument();
  expect(state.check).not.toHaveBeenCalled();
});
it("cannot spend without independent questions", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, can_measure: false, affordable: false, cases: 0 });
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(await screen.findByText(/Can’t be measured/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm and check the draft" })).toBeDisabled();
});
it("uses the existing human review and add flow", async () => {
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(
    screen.getByRole("button", { name: "Review the draft and decide whether to add it" }),
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close review" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(state.check).not.toHaveBeenCalled();
});
it("keeps the knowledge verdict separate even after the draft disappears", () => {
  state.topics = false;
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByText("Better: fixes 2, breaks nothing")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the full check" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/k1",
  );
});
it("does not present an invalidated result as an improvement", () => {
  state.invalidated = true;
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByText(/The draft changed or was removed/)).toBeInTheDocument();
  expect(screen.queryByText("Better: fixes 2, breaks nothing")).not.toBeInTheDocument();
});
it("shows a failed check instead of waiting forever", () => {
  state.runStatus = "failed";
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByRole("alert")).toHaveTextContent(/did not produce a usable result/);
});
it("shows an estimate error without starting paid work", async () => {
  state.estimate.mockRejectedValue(new Error("Unavailable"));
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(state.check).not.toHaveBeenCalled();
});

it("explains why an older draft without tracked source inputs cannot be tested", async () => {
  state.estimate.mockResolvedValue({
    ...QUOTE,
    can_measure: false,
    affordable: false,
    cases: 0,
    reason: "untracked_draft_sources",
  });
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(
    await screen.findByText(/this older draft did not record all its source questions/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm and check the draft" })).toBeDisabled();
});
