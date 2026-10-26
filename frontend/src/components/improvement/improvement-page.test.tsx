import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Improvement } from "@/types/improvement";
import { ImprovementPage } from "./improvement-page";
import { hunk } from "@/test-utils/authoring";
import type { Hunk } from "@/types/authoring";
const actions = vi.hoisted(() => ({
  estimateContinuation: { mutateAsync: vi.fn(), isPending: false },
  continueSession: { mutateAsync: vi.fn(), isPending: false },
  discard: { mutateAsync: vi.fn(), isPending: false },
  estimateSelection: { mutateAsync: vi.fn(), isPending: false },
  checkSelection: { mutateAsync: vi.fn(), isPending: false },
  cancel: { mutateAsync: vi.fn(), isPending: false },
  retry: { mutateAsync: vi.fn(), isPending: false },
  selectRound: { mutateAsync: vi.fn(), isPending: false },
  finish: { mutateAsync: vi.fn(), isPending: false },
  estimateAttribution: { mutateAsync: vi.fn(), isPending: false },
  attribute: { mutateAsync: vi.fn(), isPending: false },
}));
const state = vi.hoisted(() => ({
  agentLoading: false,
  agentError: null as Error | null,
  sessionLoading: false,
  sessionError: null as Error | null,
  authoringLoading: false,
  authoringError: null as Error | null,
  authoringRefetch: vi.fn(),
  sessionRefetch: vi.fn(),
  edit: true,
  runs: true,
  publish: true,
  session: null as Improvement | null,
  hunks: [] as Hunk[],
  topics: [] as { id: string; label: string; has_draft: boolean; can_edit: boolean }[],
  environments: [] as {
    id: string;
    name: string;
    tracks_latest: boolean;
    guard_suite_ids: string[];
  }[],
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgent: () => ({
    isLoading: state.agentLoading,
    error: state.agentError,
    agent: { id: "a1", name: "Refund desk", can_edit: state.edit, can_publish: state.publish },
  }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.runs }) }));
vi.mock("@/hooks/use-authoring", () => ({
  useAgentAuthoring: () => ({
    authoring: { batch: { id: "b1", hunks: state.hunks } },
    isLoading: state.authoringLoading,
    error: state.authoringError,
    refetch: state.authoringRefetch,
  }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    ...actions,
    session: state.session,
    error: state.sessionError,
    isLoading: state.sessionLoading,
    refetch: state.sessionRefetch,
  }),
}));
vi.mock("./knowledge-drafts", () => ({ KnowledgeDrafts: () => null }));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({ topics: state.topics, error: null }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasetCases: () => ({ cases: [], total: 12, isLoading: false, error: null }),
}));
vi.mock("@/hooks/use-agent-environments", () => ({
  useAgentEnvironments: () => ({ environments: state.environments }),
}));
vi.mock("./start-session", () => ({ StartSession: () => <p>Start fixture</p> }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({ run: null, error: null }),
  useEvalComparison: () => ({ comparison: null }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.agentLoading = false;
  state.agentError = null;
  state.sessionLoading = false;
  state.sessionError = null;
  state.authoringLoading = false;
  state.authoringError = null;
  state.edit = true;
  state.runs = true;
  state.publish = true;
  state.hunks = [];
  state.topics = [];
  state.environments = [];
  state.session = {
    offer_automatic_check: true,
    id: "s1",
    agent_id: "a1",
    status: "ready",
    stage: "judging",
    created_by_user_id: "u1",
    improver_agent_id: null,
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
});
it("blocks finishing when a selected new skill requires missing access", async () => {
  state.hunks = [hunk({ kind: "create_skill", blocked: "create_skill_permission" })];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  expect(screen.getByRole("alert")).toHaveTextContent(/current access/);
  expect(screen.getByRole("button", { name: "Accept and publish" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Keep as draft" })).toBeDisabled();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
});
it("reopens the result and requires confirmation before publishing", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("Better: fixes 3, breaks nothing")).toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  const publish = screen.getByRole("button", { name: "Accept and publish" });
  expect(publish).toBeDisabled();
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  await userEvent.click(publish);
  expect(actions.finish.mutateAsync).toHaveBeenCalledWith({
    confirmed: true,
    publish: true,
    automatic_check: true,
  });
});
it("keeps a draft and lets the person decline automatic checks", async () => {
  state.publish = false;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  expect(screen.queryByRole("button", { name: "Accept and publish" })).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  await userEvent.click(screen.getByLabelText(/Check these questions automatically/));
  await userEvent.click(screen.getByRole("button", { name: "Keep as draft" }));
  expect(actions.finish.mutateAsync).toHaveBeenCalledWith({
    confirmed: true,
    publish: false,
    automatic_check: false,
  });
});
it("requires a separate confirmation of the attribution price", async () => {
  actions.estimateAttribution.mutateAsync.mockResolvedValue({
    changes: 2,
    total_usd: "0.02",
    affordable: true,
    already_started: false,
  });
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate individual checks" }));
  expect(await screen.findByText(/2 checks.*0.02/)).toBeInTheDocument();
  expect(actions.attribute.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm and test each change" }));
  expect(actions.attribute.mutateAsync).toHaveBeenCalledWith({ number: 1, estimate: "0.02" });
});
it("refuses the flow without agent edit and run access", () => {
  state.edit = false;
  const view = render(<ImprovementPage agentId="a1" sessionId="new" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/Editing this agent/);
  expect(screen.queryByText("Start fixture")).not.toBeInTheDocument();
  state.edit = true;
  state.runs = false;
  view.rerender(<ImprovementPage agentId="a1" sessionId="new" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("stops running work and explicitly retries a failed step", async () => {
  state.session!.status = "running";
  state.session!.stage = "evaluating";
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/Testing in the background/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Stop the session" }));
  expect(actions.cancel.mutateAsync).toHaveBeenCalled();
  state.session!.status = "failed";
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(
    screen.getByRole("button", { name: "Retry this step within the spending limit" }),
  );
  expect(actions.retry.mutateAsync).not.toHaveBeenCalled();
  const quote = {
    mode: "retry",
    number: 1,
    total_usd: "0.02",
    budget_usd: "1",
    affordable: true,
    candidate_hash: "hash",
  };
  actions.estimateContinuation.mutateAsync.mockResolvedValue(quote);
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  );
  expect(actions.continueSession.mutateAsync).toHaveBeenCalledWith(quote);
});

vi.mock("./understand", () => ({ Understand: () => <p>Source examples fixture</p> }));
vi.mock("./session-inputs", () => ({
  StartSignals: () => null,
  TestQuestions: () => <p>Pinned questions fixture</p>,
  Today: () => <p>Baseline fixture</p>,
}));

it("keeps changed inclusion choices across steps and blocks accepting the old measurement", async () => {
  state.hunks = [hunk({ id: "h1" }), hunk({ id: "h2" })];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(screen.getByText(/The selection changed/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(screen.getByRole("button", { name: "Accept these changes" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  expect(screen.getByRole("checkbox", { name: "Include change 2 in the test" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(screen.queryByText(/The selection changed/)).not.toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
});
it("can read an early session without a selected round", () => {
  state.session!.status = "queued";
  state.session!.stage = null;
  state.session!.best_iteration_id = null;
  state.session!.iterations = [];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("Source examples fixture")).toBeInTheDocument();
});

it("lets the person inspect a pinned step directly without claiming it published", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  const questions = screen.getByRole("button", { name: "Test set" });
  expect(questions).toHaveAccessibleDescription("Done");
  await userEvent.click(questions);
  expect(screen.getByText("Pinned questions fixture")).toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Result" }));
  expect(screen.getByText("Better: fixes 3, breaks nothing")).toBeInTheDocument();
});

it("reopens the publication link without offering another publish", () => {
  state.session!.status = "published";
  state.session!.published_version = 4;
  state.session!.published_version_id = "v4";
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("link", { name: "Open version 4" })).toHaveAttribute(
    "href",
    "/agents/a1?tab=history&from=4&to=4",
  );
  expect(screen.queryByRole("button", { name: "Accept and publish" })).not.toBeInTheDocument();
});
it("ends on a Done screen that says a later break will be reported", () => {
  state.session!.status = "published";
  state.session!.published_version = 4;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("region", { name: "Done" })).toHaveTextContent(
    "We'll tell you if it breaks later.",
  );
});
it("says where a guarded environment switches only for a publisher", async () => {
  state.session!.next_version = 4;
  state.environments = [
    { id: "e1", name: "Production", tracks_latest: true, guard_suite_ids: ["s1"] },
  ];
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  expect(
    screen.getByText("Production switches to version 4 after the automatic check passes."),
  ).toBeInTheDocument();
  state.publish = false;
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByText(/Production switches/)).not.toBeInTheDocument();
});
it("opens the result with one sentence for the agent and one for the knowledge base", async () => {
  state.topics = [{ id: "t1", label: "Shipping", has_draft: true, can_edit: true }];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(
    screen.getByText("In the agent: 3 questions newly fixed, 0 newly broken."),
  ).toBeInTheDocument();
  expect(screen.getByText("In the knowledge base: 1 document to review.")).toBeInTheDocument();
  expect(screen.getByText("Show details: test a knowledge draft")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  await userEvent.click(screen.getByRole("button", { name: "See the result" }));
  expect(screen.getByText(/3 questions newly fixed/)).toBeInTheDocument();
});
it("shows saved draft completion and the exact next version before publishing", async () => {
  state.session!.next_version = 4;
  state.session!.offer_automatic_check = false;
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  expect(screen.getByRole("button", { name: "Publish version 4" })).toBeDisabled();
  expect(screen.queryByLabelText(/Check these questions automatically/)).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  await userEvent.click(screen.getByRole("button", { name: "Keep as draft" }));
  expect(actions.finish.mutateAsync).toHaveBeenCalledWith({
    confirmed: true,
    publish: false,
    automatic_check: false,
  });
  state.session!.status = "accepted";
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/selected changes are saved in the draft/)).toBeInTheDocument();
});
it("reports unavailable suggestions and allows retrying a failed read", async () => {
  state.session!.iterations[0]!.batch_id = "replaced";
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(screen.getByText(/suggestions are no longer available/)).toBeInTheDocument();
  state.authoringLoading = true;
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/Waiting for the selected suggestions/)).toBeInTheDocument();
  state.authoringLoading = false;
  state.authoringError = new Error("suggestions failed");
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.authoringRefetch).toHaveBeenCalled();
});
it("keeps a failed acceptance visible and shows an empty changes step", async () => {
  actions.finish.mutateAsync.mockRejectedValueOnce(new Error("publish refused"));
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Accept these changes" }));
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  await userEvent.click(screen.getByRole("button", { name: "Accept and publish" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("publish refused");
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.getByText(/couldn't find a change that fits/)).toBeInTheDocument();
  expect(screen.getByText("Attempt 1: the changes made it better.")).toBeInTheDocument();
});
it("shows loading, refusal and retry states for actual resource reads", async () => {
  state.agentLoading = true;
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByText("Better: fixes 3, breaks nothing")).not.toBeInTheDocument();
  state.agentLoading = false;
  state.agentError = new Error("agent unavailable");
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("agent unavailable")).toBeInTheDocument();
  state.agentError = null;
  state.sessionLoading = true;
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  state.sessionLoading = false;
  state.sessionError = new Error("session unavailable");
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.sessionRefetch).toHaveBeenCalled();
});

it("returns to the actual working step after confirming a selected check", async () => {
  state.hunks = [hunk({ id: "h1" })];
  actions.estimateSelection.mutateAsync.mockResolvedValue({
    total_usd: "0.04",
    affordable: true,
    candidate_hash: "hash",
  });
  actions.checkSelection.mutateAsync.mockResolvedValue(state.session);
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm and check selected changes" }),
  );
  expect(actions.checkSelection.mutateAsync).toHaveBeenCalled();
  expect(screen.getByText("Better: fixes 3, breaks nothing")).toBeInTheDocument();
});

it.each([
  ["inconclusive", { fixed: null, broken: null }],
  ["regression", { fixed: 1, broken: 2 }],
  ["no_change", {}],
] as const)("does not highlight acceptance for %s or missing measurements", (verdict, detail) => {
  state.session!.iterations[0]!.verdict = verdict;
  state.session!.iterations[0]!.verdict_detail = detail;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("button", { name: "Accept these changes" })).not.toHaveClass(
    "bg-primary",
  );
});
it("can inspect earlier rounds while another round is running", async () => {
  const first = state.session!.iterations[0]!;
  state.session!.iterations.push({ ...first, id: "r2", number: 2, verdict: null });
  state.session!.iteration = 2;
  state.session!.status = "running";
  state.session!.stage = "proposing";
  state.session!.best_iteration_id = "r1";
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/preparing changes/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(screen.getByText("Testing the changes")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Result" }));
  expect(screen.getByText(/Attempt 1/)).toBeInTheDocument();
});

it("opens the start screen for an authorized editor", () => {
  render(<ImprovementPage agentId="a1" sessionId="new" />);
  expect(screen.getByText("Start fixture")).toBeInTheDocument();
});
it("keeps a provider failure and recorded round visible without a selected best round", () => {
  state.session!.status = "failed";
  state.session!.stage = "evaluating";
  state.session!.error = "The provider could not complete this check";
  state.session!.best_iteration_id = null;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("alert")).toHaveTextContent("The provider could not complete this check");
  expect(screen.getByText("Attempt 1 of 3")).toBeInTheDocument();
});
