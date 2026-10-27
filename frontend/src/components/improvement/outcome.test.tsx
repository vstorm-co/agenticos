import { render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { comparison, FLIP, SUMMARY } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalComparison } from "@/types/eval-runs";
import {
  AcceptSummary,
  GuardNote,
  KnowledgeDocuments,
  ResultSummary,
  useSessionTopics,
} from "./outcome";
import { ReadOnlyProvider } from "./read-only";

type Topic = {
  id: string;
  status: string;
  label: string;
  examples: string[];
  knowledge_base_name: string;
  has_draft: boolean;
  can_edit: boolean;
  draft_askers?: number | null;
  drafting?: boolean;
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
  topicsLoading: false,
  evidenceTopics: ["t1", "t2", "t3"] as (string | null)[],
  compared: null as EvalComparison | null,
  environments: [] as Environment[],
  suites: [] as { id: string }[],
  defer: vi.fn(),
  refetchTopics: vi.fn(),
  refetchEvidence: vi.fn(),
  draft: vi.fn(),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({
    topics: state.topics,
    error: state.topicsError,
    isLoading: state.topicsLoading,
    refetch: state.refetchTopics,
  }),
  useDraftKnowledgeGap: () => ({ mutate: state.draft, isPending: false }),
  useKnowledgeGapDraftEstimate: () => ({ estimate: { total_usd: "0.02" } }),
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
const topic = (id: string, extra = {}): Topic => ({
  id,
  status: "open",
  label: `Topic ${id}`,
  examples: [`Topic ${id}`, `More about ${id}?`],
  knowledge_base_name: "Policies",
  has_draft: true,
  can_edit: true,
  ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  state.topicsLoading = false;
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

it("counts confirmed changes large, unconfirmed ones beside them, and links the topics", () => {
  state.compared = comparison({
    cases: [
      { ...FLIP, case_id: "c1", flip: "fixed", confirmed: false },
      { ...FLIP, case_id: "c2", flip: "fixed", confirmed: false },
      { ...FLIP, case_id: "c3", flip: "regression", confirmed: true },
    ],
  });
  const view = render(<ResultSummary session={SESSION} round={ROUND} />);
  const tiles = screen.getByRole("group", {
    name: "In the agent: 3 questions newly fixed, 0 newly broken. In the knowledge base: 3 topics missing.",
  });
  const fixed = within(tiles).getByText("Newly fixed").closest("div.flex-col")!;
  expect(fixed).toHaveTextContent("3");
  expect(fixed).toHaveTextContent("+2 not confirmed");
  expect(within(tiles).getByText("Newly broken").closest("div.flex-col")).not.toHaveTextContent(
    "not confirmed",
  );
  expect(
    screen.getByText(
      "Not confirmed: the answer changed once, but not the same way when asked again.",
    ),
  ).toBeInTheDocument();
  // Every open topic of the session counts, drafted or not, whoever may change it.
  const topics = within(tiles).getByText("Topics missing knowledge").closest("a")!;
  expect(topics).toHaveTextContent("3");
  expect(topics).toHaveAttribute("href", "#improvement-documents");
  view.rerender(
    <ResultSummary session={SESSION} round={{ ...ROUND, verdict_detail: { fixed: null } }} />,
  );
  expect(
    screen.getByRole("group", { name: /^In the agent: no measured result yet\./ }),
  ).toBeInTheDocument();
  expect(screen.getByText("In the agent: no measured result yet.")).toBeInTheDocument();
  expect(screen.queryByText(/^Not confirmed:/)).toBeNull();
  state.topics = [];
  view.rerender(<ResultSummary session={SESSION} round={ROUND} />);
  expect(screen.getByText("Topics missing knowledge").closest("a")).toBeNull();
});

it("counts only what is still missing, and says how much was added since", () => {
  state.topics = [
    topic("t1", { status: "covered" }),
    topic("t2", { status: "covered" }),
    topic("t3", { status: "dismissed" }),
  ];
  render(<ResultSummary session={SESSION} round={ROUND} />);
  expect(
    screen.getByRole("group", {
      name: "In the agent: 3 questions newly fixed, 0 newly broken. In the knowledge base: nothing missing, 2 added since.",
    }),
  ).toBeInTheDocument();
  const tile = screen.getByText("Topics missing knowledge").closest<HTMLElement>("div.flex-col")!;
  expect(tile).toHaveTextContent("0");
  expect(tile).toHaveTextContent("2 already added");
  expect(within(tile).queryByRole("link")).not.toBeInTheDocument();
});

it("offers Draft with its cost on an open topic the session found, outside the session's limit", () => {
  state.topics = [topic("t1", { has_draft: false })];
  render(<KnowledgeDocuments session={SESSION} />);
  expect(screen.getByRole("button", { name: "Draft · $0.02" })).toBeInTheDocument();
  expect(
    screen.getByText(
      "Drafting a document is billed to the knowledge base, outside this session's limit.",
    ),
  ).toBeInTheDocument();
});

it("holds the place of the topics while they are read, rather than saying none are missing", () => {
  state.topicsLoading = true;
  render(<KnowledgeDocuments session={SESSION} />);
  expect(screen.getByRole("status", { name: "Loading the topics…" })).toBeInTheDocument();
  expect(screen.queryByText("Nothing is missing from the knowledge base.")).not.toBeInTheDocument();
});

it("lists only this session's topics beside the changes and opens a draft inside the wizard", async () => {
  render(<KnowledgeDocuments session={{ ...SESSION, deferred_topic_ids: ["t2"] }} />);
  expect(screen.getByText("Missing from the knowledge base")).toBeInTheDocument();
  expect(screen.getByText("Topic t2")).toBeInTheDocument();
  expect(screen.getByText("Topic t3")).toBeInTheDocument();
  expect(screen.queryByText("Topic t9")).not.toBeInTheDocument();
  expect(
    screen.getAllByRole("list", { name: "Other questions on this topic" })[0],
  ).toHaveTextContent("More about t1?");
  // t3's knowledge base is not the caller's to change: it is listed, not reviewed.
  expect(screen.getAllByRole("button", { name: /Review the draft/ })).toHaveLength(2);
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
  state.topics = [topic("t1"), topic("t2")];
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
  const tiles = screen.getByRole("group", {
    name: "In the agent: version 4 will fix 3 questions, break 0, cost +2% per answer. Tested on 12 questions, 5 of them not used to write the changes.",
  });
  expect(within(tiles).getByText("+2%")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Cost per answer +2% compared with today's version, measured on the 5 questions kept aside.",
    ),
  ).toBeInTheDocument();
  expect(within(tiles).getByText("5 not used to write the changes")).toBeInTheDocument();
  state.compared = comparison({
    baseline_summary: { ...SUMMARY, cost_usd: "0" },
    candidate_summary: { ...SUMMARY, cases: 4 },
  });
  view.rerender(<AcceptSummary session={SESSION} round={ROUND} />);
  expect(
    screen.getByRole("group", {
      name: "In the agent: the new version will fix 3 questions, break 0. Tested on 12 questions, 4 of them not used to write the changes.",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("–")).toBeInTheDocument();
  view.rerender(<AcceptSummary session={SESSION} round={{ ...ROUND, eval_run_ids: [] }} />);
  expect(screen.getByText("In the agent: no measured result yet.")).toBeInTheDocument();
});

it("reads no cost or held-out count from a comparison it does not have", () => {
  state.compared = null;
  render(<AcceptSummary session={SESSION} round={ROUND} />);
  expect(
    screen.getByRole("group", { name: /break 0\. Tested on 12 questions, 0 of them/ }),
  ).toBeInTheDocument();
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

it("warns on a draft written from one person's question, beside the changes and on Accept", () => {
  state.topics = [topic("t1", { draft_askers: 1 }), topic("t2", { draft_askers: 3 })];
  const view = render(<KnowledgeDocuments session={SESSION} />);
  expect(screen.getAllByText(/^Based on one person's question/)).toHaveLength(1);
  view.rerender(<KnowledgeDocuments session={SESSION} accept />);
  expect(screen.getAllByText(/^Based on one person's question/)).toHaveLength(1);
});

it("lists the documents without adding or setting them aside once the wizard is only read", () => {
  render(
    <ReadOnlyProvider value="finished">
      <KnowledgeDocuments session={SESSION} accept />
    </ReadOnlyProvider>,
  );
  expect(screen.getByText("Topic t1")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Not now" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Review and add/ })).not.toBeInTheDocument();
});

it("offers a draft, with its cost, for a topic that has none, and says while it is written", async () => {
  state.topics = [
    topic("t1", { has_draft: false }),
    topic("t2", { has_draft: false, drafting: true }),
  ];
  render(<KnowledgeDocuments session={SESSION} />);
  await userEvent.click(screen.getByRole("button", { name: "Draft · $0.02" }));
  expect(state.draft).toHaveBeenCalledWith("t1");
  expect(screen.getByRole("status")).toHaveTextContent("Drafting…");
  expect(screen.queryByRole("button", { name: /Review/ })).not.toBeInTheDocument();
});

it("counts on Accept only the drafted topics, and offers drafting the rest there too", () => {
  state.topics = [topic("t1"), topic("t2", { has_draft: false })];
  render(<KnowledgeDocuments session={SESSION} accept />);
  expect(screen.getByText("In the knowledge base: 1 document to add")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Draft · $0.02" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Not now" })).toHaveLength(2);
});

it("shows where each draft stands but offers no drafting once the wizard is only read", () => {
  state.topics = [
    topic("t1", { has_draft: false }),
    topic("t2", { draft_stale: true }),
    topic("t3", { has_draft: false, draft_failed: true }),
  ];
  render(
    <ReadOnlyProvider value="viewOnly">
      <KnowledgeDocuments session={SESSION} />
    </ReadOnlyProvider>,
  );
  expect(screen.getByText("Topic t1")).toBeInTheDocument();
  expect(screen.getByText("The knowledge base changed after this draft")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("The draft could not be written.");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("finds the session's open topics, drafted or not, and nobody else's", () => {
  state.topics = [
    topic("t1"),
    topic("t2", { has_draft: false }),
    topic("t3", { status: "covered" }),
    topic("t9", { has_draft: false }),
  ];
  const { result } = renderHook(() => useSessionTopics(SESSION));
  expect(result.current.topics.map((item) => item.id)).toEqual(["t1", "t2"]);
  expect(result.current.error).toBeNull();
});
