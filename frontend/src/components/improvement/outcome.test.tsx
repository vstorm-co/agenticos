import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { comparison, SUMMARY } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalComparison } from "@/types/eval-runs";
import { AcceptSummary, DoneScreen, GuardNote, KnowledgeDocuments, ResultSummary } from "./outcome";

type Topic = {
  id: string;
  label: string;
  knowledge_base_name: string;
  has_draft: boolean;
  can_edit: boolean;
};
type Environment = {
  id: string;
  name: string;
  version: number;
  tracks_latest: boolean;
  guard_suite_ids: string[];
};

const state = vi.hoisted(() => ({
  topics: [] as Topic[],
  topicsError: null as Error | null,
  evidenceTopics: ["t1", "t2", "t3"] as (string | null)[],
  compared: null as EvalComparison | null,
  environments: [] as Environment[],
  suites: [] as { id: string }[],
  defer: vi.fn(),
  refetchTopics: vi.fn(),
  refetchEvidence: vi.fn(),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({
    topics: state.topics,
    error: state.topicsError,
    refetch: state.refetchTopics,
  }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({ deferTopic: { mutateAsync: state.defer, isPending: false } }),
  useImprovementEvidence: () => ({
    evidence: {
      items: state.evidenceTopics.map((topic, index) => ({ run_id: `r${index}`, topic_id: topic })),
    },
    error: null,
    refetch: state.refetchEvidence,
  }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasetCases: () => ({ cases: [], total: 12 }),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalComparison: () => ({ comparison: state.compared }),
}));
vi.mock("@/hooks/use-agent-environments", () => ({
  useAgentEnvironments: () => ({ environments: state.environments }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useAgentEvalSuites: () => ({ suites: state.suites }),
}));
vi.mock("@/components/knowledge-gaps/knowledge-gap-dialog", () => ({
  KnowledgeGapDialog: ({
    topicId,
    onClose,
    wizard,
  }: {
    topicId: string;
    onClose: () => void;
    wizard?: boolean;
  }) => (
    <button onClick={onClose}>
      Close draft {topicId}
      {wizard ? " in the wizard" : ""}
    </button>
  ),
}));

const ROUND = SESSION.iterations[0]!;
const topic = (id: string, extra = {}) => ({
  id,
  label: `Topic ${id}`,
  knowledge_base_name: "Policies",
  has_draft: true,
  can_edit: true,
  ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  state.topics = [topic("t1"), topic("t2"), topic("t3", { can_edit: false }), topic("t9")];
  state.topicsError = null;
  state.evidenceTopics = ["t1", "t2", "t3", null];
  state.environments = [];
  state.suites = [];
  state.defer.mockResolvedValue(SESSION);
  state.compared = comparison({
    baseline_summary: { ...SUMMARY, cases: 5, cost_usd: "0.05" },
    candidate_summary: { ...SUMMARY, cases: 5, cost_usd: "0.051" },
  });
});

it("sums up the result for the agent and for this session's knowledge documents", () => {
  const view = render(<ResultSummary session={SESSION} round={ROUND} />);
  expect(
    screen.getByText("In the agent: 3 questions newly fixed, 0 newly broken."),
  ).toBeInTheDocument();
  expect(screen.getByText("In the knowledge base: 2 documents to review.")).toBeInTheDocument();
  view.rerender(
    <ResultSummary session={SESSION} round={{ ...ROUND, verdict_detail: { fixed: null } }} />,
  );
  expect(screen.getByText("In the agent: no measured result yet.")).toBeInTheDocument();
});

it("lists only this session's drafts beside the changes and opens one inside the wizard", async () => {
  render(<KnowledgeDocuments session={{ ...SESSION, deferred_topic_ids: ["t2"] }} />);
  expect(screen.getByText("Missing from the knowledge base")).toBeInTheDocument();
  expect(screen.getByText("Topic t2")).toBeInTheDocument();
  expect(screen.queryByText("Topic t3")).not.toBeInTheDocument();
  expect(screen.queryByText("Topic t9")).not.toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: /Review the draft/ })[0]!);
  await userEvent.click(screen.getByRole("button", { name: "Close draft t1 in the wizard" }));
  expect(screen.queryByRole("button", { name: /Close draft/ })).not.toBeInTheDocument();
});

it("says nothing is missing, and offers to read the drafts again after a failure", async () => {
  state.topics = [];
  state.topicsError = new Error("Forbidden");
  render(<KnowledgeDocuments session={SESSION} />);
  expect(screen.getByText("Nothing is missing from the knowledge base.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.refetchTopics).toHaveBeenCalled();
  expect(state.refetchEvidence).toHaveBeenCalled();
});

it("keeps a document set aside with Not now off the list, and says when that fails", async () => {
  const view = render(<KnowledgeDocuments session={SESSION} accept />);
  expect(screen.getByText("In the knowledge base: 2 documents to add")).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "Not now" })[0]!);
  expect(state.defer).toHaveBeenCalledWith({ topicId: "t1", later: true });
  view.rerender(<KnowledgeDocuments session={{ ...SESSION, deferred_topic_ids: ["t1"] }} accept />);
  expect(screen.getByText("In the knowledge base: 1 document to add")).toBeInTheDocument();
  expect(screen.queryByText("Topic t1")).not.toBeInTheDocument();
  state.defer.mockRejectedValueOnce(new Error("Session decided"));
  await userEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Session decided");
  await userEvent.click(screen.getByRole("button", { name: "Review and add" }));
  expect(screen.getByRole("button", { name: "Close draft t2 in the wizard" })).toBeInTheDocument();
});

it("states what the new version fixes, breaks and costs, and what it was tested on", () => {
  const view = render(<AcceptSummary session={{ ...SESSION, next_version: 4 }} round={ROUND} />);
  expect(
    screen.getByText(
      "In the agent: version 4 will fix 3 questions, break 0, cost +2% per answer. Tested on 12 questions, 5 of them not used to write the changes.",
    ),
  ).toBeInTheDocument();
  state.compared = comparison({
    baseline_summary: { ...SUMMARY, cost_usd: "0" },
    candidate_summary: { ...SUMMARY, cases: 4 },
  });
  view.rerender(<AcceptSummary session={SESSION} round={ROUND} />);
  expect(
    screen.getByText(
      "In the agent: the new version will fix 3 questions, break 0. Tested on 12 questions, 4 of them not used to write the changes.",
    ),
  ).toBeInTheDocument();
  view.rerender(<AcceptSummary session={SESSION} round={{ ...ROUND, eval_run_ids: [] }} />);
  expect(screen.getByText("In the agent: no measured result yet.")).toBeInTheDocument();
});

it("reads no cost or held-out count from a comparison it does not have", () => {
  state.compared = null;
  render(<AcceptSummary session={SESSION} round={ROUND} />);
  expect(screen.getByText(/break 0\. Tested on 12 questions, 0 of them/)).toBeInTheDocument();
});

it("says what publishing does in each place people use the agent", () => {
  state.environments = [
    { id: "e1", name: "Production", version: 3, tracks_latest: true, guard_suite_ids: ["s1"] },
    { id: "e2", name: "Staging", version: 3, tracks_latest: true, guard_suite_ids: [] },
    { id: "e3", name: "Pinned", version: 2, tracks_latest: false, guard_suite_ids: ["s1"] },
  ];
  render(<GuardNote agentId="a1" version={4} />);
  expect(
    screen.getByText(
      "Production switches to version 4 after the automatic check passes, usually within a few minutes.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Staging switches to version 4 right away.")).toBeInTheDocument();
  expect(screen.getByText("Pinned stays on version 2.")).toBeInTheDocument();
});

it("ends on a Done screen that promises a warning only when a check watches the agent", () => {
  state.suites = [{ id: "s1" }];
  const view = render(
    <DoneScreen session={{ ...SESSION, status: "published", published_version: 4 }} />,
  );
  expect(screen.getByText("Version 4 is published.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open version 4" })).toHaveAttribute(
    "href",
    "/agents/a1?tab=history&from=4&to=4",
  );
  expect(screen.getByText("We'll tell you if it breaks later.")).toBeInTheDocument();
  state.suites = [];
  view.rerender(<DoneScreen session={{ ...SESSION, status: "accepted" }} />);
  expect(screen.getByText(/saved in the draft/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Open version/ })).not.toBeInTheDocument();
  expect(screen.queryByText("We'll tell you if it breaks later.")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Set up an automatic check" })).toHaveAttribute(
    "href",
    "/agents/a1?tab=evals",
  );
});
