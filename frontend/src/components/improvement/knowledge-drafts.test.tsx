import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Improvement, KnowledgeCheckEstimate } from "@/types/improvement";
import { KnowledgeDrafts } from "./knowledge-drafts";
const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  check: vi.fn(),
  refetch: vi.fn().mockResolvedValue({}),
  topics: true,
  runStatus: "completed",
  invalidated: false,
  retrievalInvalid: false,
  topicError: null as Error | null,
  listError: null as Error | null,
  runError: null as Error | null,
  comparisonError: null as Error | null,
  verdict: "better",
  supported: false,
  noRun: false,
  total: 8,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    refetch: state.refetch,
    estimateKnowledge: { mutateAsync: state.estimate, isPending: false },
    checkKnowledge: { mutateAsync: state.check, isPending: false },
  }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({
    error: state.listError,
    topics: state.topics ? [{ id: "t1", has_draft: true, can_edit: true, label: "Returns" }] : [],
  }),
  useKnowledgeGap: () => ({
    error: state.topicError,
    topic: {
      draft: {
        title: "Return policy",
        content: "Returns take 30 days.",
        sources: state.supported ? [{ kind: "document" }] : [],
      },
    },
  }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasetCases: () => ({
    cases: [
      ...[
        "Return window?",
        "Gift order?",
        "Shipping fee?",
        "Weekend days?",
        "Arrival date?",
        "Source question?",
        "Copied source question?",
      ].map((input, index) => ({
        case_id: `q${index + 1}`,
        input,
        improvement_partition: "holdout",
      })),
      { case_id: "q8", input: "Learning example", improvement_partition: "train" },
    ],
    total: state.total,
  }),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({
    error: state.runError,
    run: state.noRun
      ? null
      : {
          status: state.runStatus,
          proposal_check: { knowledge: { supported: false, invalidated: state.invalidated } },
        },
  }),
  useEvalComparison: () => ({
    error: state.comparisonError,
    comparison: {
      verdict: state.retrievalInvalid ? "invalid" : state.verdict,
      invalid_reason_code: state.retrievalInvalid ? "knowledge_not_retrieved" : null,
      fixed_confirmed: 2,
      regressions_confirmed: 0,
    },
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
  state.retrievalInvalid = false;
  state.topicError = state.listError = state.runError = state.comparisonError = null;
  state.verdict = "better";
  state.supported = state.noRun = false;
  state.total = 8;
  state.estimate.mockResolvedValue(QUOTE);
  state.check.mockResolvedValue({ id: "k1" });
});
async function choose() {
  await userEvent.selectOptions(screen.getByRole("combobox"), "t1");
  for (const checkbox of screen.getAllByRole("checkbox")) {
    if (!checkbox.hasAttribute("disabled")) await userEvent.click(checkbox);
  }
}
it("requires a separately priced confirmation and keeps fact verification visible", async () => {
  render(<KnowledgeDrafts session={SESSION} />);
  expect(screen.getByLabelText("Learning example")).toBeDisabled();
  await choose();
  expect(screen.getByText(/Unsupported — verify the facts/)).toBeInTheDocument();
  expect(screen.getByText(/Assuming search finds this passage/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(await screen.findByText(/5 independent questions/)).toHaveTextContent(/2 left out/);
  expect(state.check).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm and check the draft" }));
  expect(state.check).toHaveBeenCalledWith({
    topic_id: "t1",
    mode: "context",
    round: 1,
    case_ids: ["q1", "q2", "q3", "q4", "q5", "q6", "q7"],
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

it("requires a fresh quote after switching to actual retrieval", async () => {
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  await screen.findByText(/5 independent questions/);
  await userEvent.click(screen.getByRole("button", { name: "Test whether search finds it" }));
  expect(
    screen.queryByRole("button", { name: "Confirm and check the draft" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/The draft joins search only for this check/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  expect(state.estimate).toHaveBeenLastCalledWith({
    topic_id: "t1",
    mode: "retrieval",
    round: 1,
    case_ids: ["q1", "q2", "q3", "q4", "q5", "q6", "q7"],
  });
});
it("does not call a high pass count an improvement when search failed to return the draft", () => {
  state.retrievalInvalid = true;
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByText(/No demonstrated improvement from the draft/)).toBeInTheDocument();
  expect(screen.queryByText("Better: fixes 2, breaks nothing")).not.toBeInTheDocument();
  expect(state.refetch).toHaveBeenCalled();
});

it("can review and check knowledge-only sessions without an agent proposal", async () => {
  render(
    <KnowledgeDrafts
      session={{
        ...SESSION,
        status: "stopped",
        stage: "drafting",
        stop_reason: "knowledge_only",
        best_iteration_id: null,
        iterations: SESSION.iterations.map((item) => ({ ...item, batch_id: null, verdict: null })),
      }}
    />,
  );
  await choose();
  expect(
    screen.getByRole("button", { name: "Review the draft and decide whether to add it" }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
  await screen.findByText(/5 independent questions/);
  expect(state.estimate).toHaveBeenCalledWith(
    expect.objectContaining({ round: 1, topic_id: "t1" }),
  );
});

it("keeps completed drafts available when the drafting job failed partway", () => {
  render(
    <KnowledgeDrafts
      session={{
        ...SESSION,
        timeline: [
          {
            action: "improvement.drafting_failed",
            at: SESSION.created_at,
            stage: "drafting",
            status: "running",
            reason: null,
          },
        ],
      }}
    />,
  );
  expect(screen.getByText(/couldn’t finish preparing the knowledge drafts/)).toBeInTheDocument();
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});

it("pages through the pinned questions without starting a check", async () => {
  state.total = 40;
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  const back = screen.getByRole("button", { name: "Previous questions" });
  const next = screen.getByRole("button", { name: "Next questions" });
  expect(back).toBeDisabled();
  await userEvent.click(next);
  expect(back).toBeEnabled();
  expect(next).toBeDisabled();
  await userEvent.click(back);
  expect(back).toBeDisabled();
  expect(state.check).not.toHaveBeenCalled();
});
it("reports a draft read failure and keeps the check from being fabricated", async () => {
  state.topicError = new Error("Draft unavailable");
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("shows list and completed-check read failures", () => {
  state.listError = new Error("Topics unavailable");
  state.runError = new Error("Check unavailable");
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getAllByRole("alert")).toHaveLength(2);
});
it.each(["queued", "running"])("shows %s checks as background work", (status) => {
  state.runStatus = status;
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText("Better: fixes 2, breaks nothing")).not.toBeInTheDocument();
});
it("waits for a not-yet-loaded check without inventing its outcome", () => {
  state.noRun = true;
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
});
it.each(["worse", "invalid", "unchanged"])(
  "renders a %s completed knowledge comparison",
  (verdict) => {
    state.verdict = verdict;
    render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
    expect(screen.queryByText("Better: fixes 2, breaks nothing")).not.toBeInTheDocument();
  },
);
it.each(["embedding_unavailable", "embedding_price_unavailable", "knowledge_search_disabled"])(
  "explains %s before any paid draft check",
  async (reason) => {
    state.estimate.mockResolvedValue({ ...QUOTE, can_measure: false, affordable: false, reason });
    render(<KnowledgeDrafts session={SESSION} />);
    await choose();
    await userEvent.click(screen.getByRole("button", { name: "Estimate checking the draft" }));
    expect(
      await screen.findByRole("button", { name: "Confirm and check the draft" }),
    ).toBeDisabled();
    expect(state.check).not.toHaveBeenCalled();
  },
);
it("shows verified documentary support without the unsupported warning", async () => {
  state.supported = true;
  render(<KnowledgeDrafts session={SESSION} />);
  await choose();
  expect(screen.queryByText(/Unsupported — verify the facts/)).not.toBeInTheDocument();
});

it("does not show a result when its comparison could not be read", () => {
  state.comparisonError = new Error("Comparison unavailable");
  render(<KnowledgeDrafts session={{ ...SESSION, knowledge_eval_run_ids: ["k1"] }} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("Better: fixes 2, breaks nothing")).not.toBeInTheDocument();
});
