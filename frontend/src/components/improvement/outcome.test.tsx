import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { comparison, SUMMARY } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalComparison } from "@/types/eval-runs";
import { AcceptSummary, DoneScreen, GuardNote, KnowledgeDocuments, ResultSummary } from "./outcome";

const state = vi.hoisted(() => ({
  topics: [] as {
    id: string;
    label: string;
    knowledge_base_name: string;
    has_draft: boolean;
    can_edit: boolean;
  }[],
  topicsError: null as Error | null,
  compared: null as EvalComparison | null,
  environments: [] as {
    id: string;
    name: string;
    tracks_latest: boolean;
    guard_suite_ids: string[];
  }[],
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({ topics: state.topics, error: state.topicsError }),
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
vi.mock("@/components/knowledge-gaps/knowledge-gap-dialog", () => ({
  KnowledgeGapDialog: ({ topicId, onClose }: { topicId: string; onClose: () => void }) => (
    <button onClick={onClose}>Close draft {topicId}</button>
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
  state.topics = [topic("t1"), topic("t2"), topic("t3", { can_edit: false })];
  state.topicsError = null;
  state.environments = [];
  state.compared = comparison({
    baseline_summary: { ...SUMMARY, cases: 5, cost_usd: "0.05" },
    candidate_summary: { ...SUMMARY, cases: 5, cost_usd: "0.051" },
  });
});

it("sums up the result for the agent and for the knowledge base", () => {
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

it("lists knowledge drafts beside the changes and opens one for review", async () => {
  render(<KnowledgeDocuments agentId="a1" />);
  expect(screen.getByText("Missing from the knowledge base")).toBeInTheDocument();
  expect(screen.queryByText("Topic t3")).not.toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: /Review the draft/ })[0]!);
  await userEvent.click(screen.getByRole("button", { name: "Close draft t1" }));
  expect(screen.queryByRole("button", { name: "Close draft t1" })).not.toBeInTheDocument();
});

it("says nothing is missing, and shows a failed read of the drafts", () => {
  state.topics = [];
  state.topicsError = new Error("Forbidden");
  render(<KnowledgeDocuments agentId="a1" />);
  expect(screen.getByText("Nothing is missing from the knowledge base.")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

it("offers each document to review and add, or to leave for now", async () => {
  render(<KnowledgeDocuments agentId="a1" accept />);
  expect(screen.getByText("In the knowledge base: 2 documents to add")).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "Not now" })[0]!);
  expect(screen.getByText("In the knowledge base: 1 document to add")).toBeInTheDocument();
  expect(screen.queryByText("Topic t1")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Review and add" }));
  expect(screen.getByRole("button", { name: "Close draft t2" })).toBeInTheDocument();
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

it("names only environments that follow new versions behind an automatic check", () => {
  state.environments = [
    { id: "e1", name: "Production", tracks_latest: true, guard_suite_ids: ["s1"] },
    { id: "e2", name: "Staging", tracks_latest: true, guard_suite_ids: [] },
    { id: "e3", name: "Pinned", tracks_latest: false, guard_suite_ids: ["s1"] },
  ];
  render(<GuardNote agentId="a1" version={4} />);
  expect(
    screen.getByText("Production switches to version 4 after the automatic check passes."),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Staging|Pinned/)).not.toBeInTheDocument();
});

it("ends on a Done screen with the published version or the kept draft", () => {
  const view = render(
    <DoneScreen session={{ ...SESSION, status: "published", published_version: 4 }} />,
  );
  expect(screen.getByRole("link", { name: "Open version 4" })).toHaveAttribute(
    "href",
    "/agents/a1?tab=history&from=4&to=4",
  );
  expect(screen.getByText("We'll tell you if it breaks later.")).toBeInTheDocument();
  view.rerender(<DoneScreen session={{ ...SESSION, status: "accepted" }} />);
  expect(screen.getByText(/saved in the draft/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Open version/ })).not.toBeInTheDocument();
});
