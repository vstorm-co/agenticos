import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IMPROVEMENT_STEPS as STEPS, improvementSteps, isReachable } from "@/lib/improvement-steps";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { ImprovementPage } from "./improvement-page";
import { hunk } from "@/test-utils/authoring";
import type { Hunk } from "@/types/authoring";
const actions = vi.hoisted(() => ({
  estimateContinuation: { mutateAsync: vi.fn(), isPending: false },
  continueSession: { mutateAsync: vi.fn(), isPending: false },
  selectChanges: { mutateAsync: vi.fn(), isPending: false },
  editChange: { mutateAsync: vi.fn(), isPending: false },
  discard: { mutateAsync: vi.fn(), isPending: false },
  estimateSelection: { mutateAsync: vi.fn(), isPending: false },
  checkSelection: { mutateAsync: vi.fn(), isPending: false },
  cancel: { mutateAsync: vi.fn(), isPending: false },
  retry: { mutateAsync: vi.fn(), isPending: false },
  selectRound: { mutateAsync: vi.fn(), isPending: false },
  finish: { mutateAsync: vi.fn(), isPending: false },
  deferTopic: { mutateAsync: vi.fn(), isPending: false },
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
  topics: [] as {
    id: string;
    label: string;
    examples?: string[];
    status?: string;
    has_draft: boolean;
    can_edit: boolean;
  }[],
  environments: [] as {
    id: string;
    name: string;
    tracks_latest: boolean;
    guard_suite_ids: string[];
  }[],
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
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
  useImprovementEvidence: () => ({
    evidence: { items: state.topics.map((topic) => ({ run_id: topic.id, topic_id: topic.id })) },
    refetch: vi.fn(),
  }),
  useImprovementChanges: () => ({
    changes: state.hunks,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useAttemptChanges: () => ({ changes: state.hunks, isLoading: false, error: null }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({ useAgentEvalSuites: () => ({ suites: [] }) }));
vi.mock("./knowledge-drafts", async (actual) => ({
  ...(await actual<typeof import("./knowledge-drafts")>()),
  KnowledgeDrafts: () => <p>Draft check fixture</p>,
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({ topics: state.topics, error: null }),
}));
vi.mock("@/components/knowledge-gaps/knowledge-gap-draft-status", () => ({
  KnowledgeGapDraftStatus: () => null,
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
  window.history.replaceState({}, "", "/");
  actions.estimateContinuation.mutateAsync.mockResolvedValue({
    mode: "next_step",
    number: 1,
    total_usd: "0.04",
    budget_usd: "1",
    affordable: true,
    candidate_hash: "a".repeat(64),
  });
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
it("says an attempt that did not do better finished, and what under a cent cost", () => {
  Object.assign(state.session!, {
    status: "stopped",
    stop_reason: "no_change",
    spent_usd: "0.0037",
    budget_usd: "0.850000",
  });
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  const line = screen.getByRole("region", { name: "Session" });
  expect(within(line).getByRole("status")).toHaveTextContent("Finished an attempt");
  expect(line).toHaveTextContent("$0.0037 of $0.85");
});

it("blocks finishing when a selected new skill requires missing access", async () => {
  state.hunks = [hunk({ kind: "create_skill", blocked: "create_skill_permission" })];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
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
  expect(screen.getByText(/^Attempt 1 made .+ better: 3 questions fixed/)).toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
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
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
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
  await userEvent.click(screen.getByText("Attempt 1 of 3"));
  await userEvent.click(screen.getByText("Show details"));
  expect(
    await screen.findByText(/^This attempt has 2 changes\..*about \$0\.02/),
  ).toBeInTheDocument();
  expect(actions.attribute.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Test each change" }));
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
  await userEvent.click(screen.getByRole("button", { name: "Stop the session" }));
  expect(actions.cancel.mutateAsync).toHaveBeenCalledTimes(2);
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

it("retries a failed step from another step too, and then follows the session again", async () => {
  state.session!.status = "failed";
  state.session!.stage = "evaluating";
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.queryByText("What this session came to")).toBeNull();
  actions.estimateContinuation.mutateAsync.mockResolvedValue({
    mode: "retry",
    number: 1,
    total_usd: "0.02",
    budget_usd: "1",
    affordable: true,
    candidate_hash: "hash",
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Retry this step within the spending limit" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  );
  expect(actions.continueSession.mutateAsync).toHaveBeenCalled();
  expect(await screen.findByText("What this session came to")).toBeInTheDocument();
});

vi.mock("./understand", () => ({ Understand: () => <p>Source examples fixture</p> }));
vi.mock("./session-inputs", () => ({
  StartSignals: () => null,
  TestQuestions: () => <p>Pinned questions fixture</p>,
}));

it("draws Previous step exactly like Next step, each with its arrow", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  const previous = screen.getByRole("button", { name: "Previous step" });
  const next = screen.getByRole("button", { name: "Next step" });
  expect(previous.className).toBe(next.className);
  expect(previous).not.toHaveClass("bg-primary");
  expect(previous.querySelector("svg.lucide-chevron-left")).toHaveAttribute("aria-hidden", "true");
  expect(next.querySelector("svg.lucide-chevron-right")).toHaveAttribute("aria-hidden", "true");
});

it("keeps changed inclusion choices across steps and blocks accepting the old measurement", async () => {
  state.hunks = [hunk({ id: "h1" }), hunk({ id: "h2" })];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(screen.getByText(/The selection changed/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(screen.getByRole("button", { name: "Review and accept the changes" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  await userEvent.click(screen.getByRole("button", { name: "Previous step" }));
  expect(screen.getByRole("checkbox", { name: "Include change 2 in the test" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(screen.queryByText(/The selection changed/)).not.toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
});
it("says a waiting session is still reading what went wrong instead of listing nothing", () => {
  state.session!.status = "queued";
  state.session!.stage = null;
  state.session!.best_iteration_id = null;
  state.session!.iterations = [];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/Reading what went wrong/)).toBeInTheDocument();
  expect(screen.queryByText("Source examples fixture")).not.toBeInTheDocument();
});

it("lets the person inspect a done step directly without claiming it published", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  const understand = screen.getByRole("button", { name: "Understand" });
  expect(understand).toHaveAccessibleDescription("Done");
  await userEvent.click(understand);
  expect(screen.getByText("Pinned questions fixture")).toBeInTheDocument();
  expect(actions.finish.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Result" }));
  expect(screen.getByText(/^Attempt 1 made .+ better: 3 questions fixed/)).toBeInTheDocument();
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
it("ends on what was decided, and offers nothing that would change the session", () => {
  state.session!.status = "published";
  state.session!.published_version = 4;
  state.session!.timeline = [
    {
      action: "improvement.published",
      at: "2026-10-24T13:00:00Z",
      stage: null,
      status: "published",
      reason: null,
      actor_name: "Ada",
    },
  ];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  const decided = screen.getByRole("region", { name: "What was decided" });
  expect(decided).toHaveTextContent("Published as version 4");
  expect(decided).toHaveTextContent(/By Ada/);
  expect(screen.getByText(/This improvement is finished/)).toBeInTheDocument();
  for (const name of ["Stop the session", "Keep as draft", "Discard", /Improve again/]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  // The step bar still opens every step; only the decision is gone.
  expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(1);
});
it("lets a reader of the agent and its runs read an open session without changing it", () => {
  state.edit = false;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/Changing it needs edit access to the agent/)).toBeInTheDocument();
  expect(screen.queryByText(/This improvement is finished/)).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(1);
});
it("says where a guarded environment switches only for a publisher", async () => {
  state.session!.next_version = 4;
  state.environments = [
    { id: "e1", name: "Production", tracks_latest: true, guard_suite_ids: ["s1"] },
  ];
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
  expect(
    screen.getByText(
      "Production switches to version 4 after the automatic check passes, usually within a few minutes.",
    ),
  ).toBeInTheDocument();
  state.publish = false;
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByText(/Production switches/)).not.toBeInTheDocument();
});
it("says the session's state and spend once, in one line above the steps", () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  const line = screen.getByRole("region", { name: "Session" });
  expect(line).toHaveTextContent("Ready for your review·$0.03 of $1.00");
  expect(within(line).getByRole("meter", { name: "Spending limit used" })).toHaveAttribute(
    "aria-valuenow",
    "3",
  );
  expect(
    line.compareDocumentPosition(screen.getByRole("navigation", { name: "Improvement steps" })),
  ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
});

it("keeps the knowledge draft check under Show details before any attempt is measured", () => {
  state.session = { ...state.session!, iterations: [], best_iteration_id: null };
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByText("Show details")).toBeNull();
  state.session = { ...state.session, knowledge_eval_run_ids: ["k1"] };
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getAllByText("Show details")).toHaveLength(1);
  expect(screen.getByText("Draft check fixture")).toBeInTheDocument();
});

it("opens the result with one sentence for the agent and one for the knowledge base", async () => {
  state.topics = [
    {
      id: "t1",
      label: "Shipping",
      examples: ["Shipping"],
      status: "open",
      has_draft: false,
      can_edit: true,
    },
  ];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(
    screen.getByRole("group", {
      name: "In the agent: 3 questions newly fixed, 0 newly broken. In the knowledge base: 1 topic missing.",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("Attempt 1 of 3").closest("details")).not.toHaveAttribute("open");
  await userEvent.click(screen.getByText("Attempt 1 of 3"));
  expect(screen.getAllByText("Show details")).toHaveLength(1);
  expect(screen.getByText("Draft check fixture")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  await userEvent.click(screen.getByRole("button", { name: "See the result" }));
  expect(screen.getByRole("group", { name: /3 questions newly fixed/ })).toBeInTheDocument();
});
it("shows saved draft completion and the exact next version before publishing", async () => {
  state.session!.next_version = 4;
  state.session!.offer_automatic_check = false;
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
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
  expect(screen.getByText(/Kept as a draft\. Publish it from the agent/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Keep as draft" })).not.toBeInTheDocument();
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
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
  await userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );
  await userEvent.click(screen.getByRole("button", { name: "Accept and publish" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("publish refused");
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.getByRole("heading", { name: "What each attempt tried" })).toBeInTheDocument();
  expect(screen.getByText("Attempt 1: the changes made it better.")).toBeInTheDocument();
});
it("shows loading, refusal and retry states for actual resource reads", async () => {
  state.agentLoading = true;
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByText(/^Attempt 1 made .+ better/)).not.toBeInTheDocument();
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
  expect(screen.getByText(/^Attempt 1 made .+ better: 3 questions fixed/)).toBeInTheDocument();
});

it.each([
  ["inconclusive", { fixed: null, broken: null }],
  ["regression", { fixed: 1, broken: 2 }],
  ["no_change", {}],
] as const)("names a chosen %s attempt as chosen rather than better", (verdict, detail) => {
  state.session!.iterations[0]!.verdict = verdict;
  state.session!.iterations[0]!.verdict_detail = detail;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText(/^You chose attempt 1 to accept\./)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Review and accept the changes" })).toBeEnabled();
});
it("follows a second attempt through Changes and Check, keeping Result shut", async () => {
  const first = state.session!.iterations[0]!;
  state.session!.iterations = [
    { ...first, verdict: "no_change" },
    { ...first, id: "r2", number: 2, batch_id: null, verdict: null },
  ];
  state.session!.iteration = 2;
  state.session!.status = "running";
  state.session!.stage = "proposing";
  state.session!.best_iteration_id = null;
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("Attempt 1: no measurable change.")).toBeInTheDocument();
  expect(screen.getByText("Attempt 2 of 3: writing different changes…")).toBeInTheDocument();
  const result = screen.getByRole("button", { name: "Result" });
  expect(result).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(result);
  expect(screen.queryByText(/Better:/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(screen.getByText("Testing the changes")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Next step" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Go to the current step" })).toBeInTheDocument();
  state.hunks = [hunk({ id: "h9" })];
  state.session = {
    ...state.session!,
    stage: "evaluating",
    iterations: [
      state.session!.iterations[0]!,
      { ...state.session!.iterations[1]!, batch_id: "b1" },
    ],
  };
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("Attempt 2 of 3 is being checked.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.getByText("Checking these changes — attempt 2 of 3")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Go to the current step" }));
  expect(screen.getByText("Attempt 2 of 3 is being checked.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Go to the current step" })).not.toBeInTheDocument();
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
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Technical details").closest("details")).toHaveTextContent(
    "The provider could not complete this check",
  );
  expect(screen.getByText("Attempt 1 of 3")).toBeInTheDocument();
});

it("says how many more questions a session needs, in words rather than the server's message", () => {
  state.session!.status = "stopped";
  state.session!.stop_reason = "no_data";
  state.session!.error = "Add 2 more held-out test questions to measure a change";
  state.session!.iterations[0]!.verdict_detail = { missing_holdout: 2 };
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(
    screen.getByText(
      /Too few questions to measure a change: 2 more questions not used to write the changes are needed\./,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Technical details")).toBeInTheDocument();
});
it("keeps one row of actions on the result: no Next step beside Accept and Try again", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.queryByRole("button", { name: "Next step" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Review and accept the changes" })).toHaveClass(
    "bg-primary",
  );
  await userEvent.click(screen.getByRole("button", { name: "Understand" }));
  expect(screen.queryByRole("button", { name: "Previous step" })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Review and accept the changes" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(screen.getByRole("button", { name: "Previous step" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Close and return later" })).toHaveAttribute(
    "href",
    "/agents/a1",
  );
});
it("moves focus to the heading of the step a person opens", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(screen.getByRole("heading", { name: "Testing the changes" })).toHaveFocus();
});
it("tells someone who may not publish why, and still lets them keep a draft", async () => {
  state.publish = false;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
  expect(screen.getByText(/Publishing needs permission to publish this agent/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Keep as draft" })).toBeInTheDocument();
});
it("refuses with a reason and a way back to the agent", () => {
  state.runs = false;
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/viewing runs are required/);
  expect(screen.getByRole("link", { name: "Open the agent" })).toHaveAttribute(
    "href",
    "/agents/a1",
  );
});
it("announces why a step failed, and lists attempts that were never tested", async () => {
  state.session!.status = "failed";
  state.session!.stop_reason = "eval";
  state.session!.best_iteration_id = null;
  const first = state.session!.iterations[0]!;
  state.session!.iterations = [
    { ...first, verdict: null },
    { ...first, id: "r2", number: 2, verdict: null, batch_id: null },
    { ...first, id: "r4", number: state.session!.max_iterations + 1, verdict: null },
  ];
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("alert")).toHaveTextContent("The test step failed.");
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.getByText("Attempt 1: changes proposed, not tested yet.")).toBeInTheDocument();
  expect(screen.getByText("Attempt 2: no change was proposed.")).toBeInTheDocument();
  expect(screen.getByText("Changes held back for another attempt, not tested")).toBeInTheDocument();
});

it("shows the changes being checked only to read, and the stop's changes to tick and edit", async () => {
  const first = state.session!.iterations[0]!;
  state.hunks = [hunk({ id: "h1" })];
  state.session = {
    ...state.session!,
    status: "running",
    stage: "evaluating",
    best_iteration_id: null,
    iterations: [{ ...first, included_hunk_ids: ["h1"], verdict: null }],
  };
  const view = render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(screen.getByText("Checking these changes — attempt 1 of 3")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Change the wording" })).not.toBeInTheDocument();
  state.session = { ...state.session, status: "waiting", stage: "filtering", next_step: "check" };
  view.rerender(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByText("This change will be tested.")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.getByText("Correct the wording if needed. The next step is priced before you press."),
  ).toBeInTheDocument();
  const next = await screen.findByRole("button", {
    name: "Next step: test the selected changes · about $0.04",
  });
  expect(next).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Change the wording" }));
  expect(next).toBeEnabled();
  await userEvent.type(screen.getByRole("textbox", { name: "Wording of change 1" }), " Briefly.");
  expect(next).toBeDisabled();
  expect(screen.getByText("Save or discard the wording first.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(next).toBeEnabled();
});

it("keeps an opened step in the address, and drops it on the way back to the current one", async () => {
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(new URLSearchParams(window.location.search).get("step")).toBe("changes");
  await userEvent.click(screen.getByRole("button", { name: "Go to the current step" }));
  expect(new URLSearchParams(window.location.search).has("step")).toBe(false);
});

it.each([
  ["changes", "an open step", "Changes"],
  ["accept", "a step a running session keeps shut", "Check"],
])("opens ?step=%s from a link, unless it is %s", (step, _, shown) => {
  if (step === "accept") {
    state.session = { ...state.session!, status: "running", stage: "evaluating" };
  }
  window.history.replaceState({}, "", `/?step=${step}`);
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("button", { name: shown }).closest("li")).toHaveAttribute(
    "aria-current",
    "step",
  );
});

it.each([
  ["classifying", "Waiting for you: look at what went wrong"],
  ["filtering", "Waiting for you: review the changes"],
] as const)("says what a session stopped after %s waits for, not that it works", (stage, line) => {
  state.session = { ...state.session!, status: "waiting", stage };
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(
    within(screen.getByRole("region", { name: "Session" })).getByRole("status"),
  ).toHaveTextContent(line);
});

it("opens Understand from an old link to the test set, rewriting the address", () => {
  state.session = { ...state.session!, status: "waiting", stage: "classifying" };
  window.history.replaceState({}, "", "/?step=testSet");
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("button", { name: "Understand" }).closest("li")).toHaveAttribute(
    "aria-current",
    "step",
  );
  expect(new URLSearchParams(window.location.search).get("step")).toBe("understand");
  expect(screen.queryByRole("button", { name: "Test set" })).not.toBeInTheDocument();
});

it("opens Check from an old link to Today, rewriting the address", () => {
  state.session = { ...state.session!, status: "running", stage: "evaluating" };
  window.history.replaceState({}, "", "/?step=today");
  render(<ImprovementPage agentId="a1" sessionId="s1" />);
  expect(screen.getByRole("button", { name: "Check" }).closest("li")).toHaveAttribute(
    "aria-current",
    "step",
  );
  expect(new URLSearchParams(window.location.search).get("step")).toBe("check");
  expect(screen.queryByRole("button", { name: "Today" })).not.toBeInTheDocument();
});

const LABELS: Record<(typeof STEPS)[number], string> = {
  understand: "Understand",
  changes: "Changes",
  check: "Check",
  result: "Result",
  accept: "Accept",
};
const WORKING =
  /Reading what went wrong|Writing the changes|writing different changes|Testing in the background|Preparing the test/;
const FINAL =
  /Source examples fixture|We couldn't find a change|What each attempt tried|The test has finished|newly fixed|Open version|Kept as draft/;

describe("every step's state matches what its panel shows", () => {
  const round = (number: number, extra: Partial<ImprovementIteration> = {}) => ({
    id: `r${number}`,
    number,
    authoring_request_id: "p1",
    batch_id: "b1",
    eval_run_ids: [],
    candidate_spec_hash: "hash",
    attribution_eval_run_ids: {},
    dropped_hunk_ids: [],
    dropped: [],
    verdict: "no_change" as const,
    verdict_detail: { fixed: 0, broken: 0 },
    cost_usd: "0.01",
    started_at: "2026-10-24T12:00:00Z",
    ended_at: null,
    ...extra,
  });
  const fresh = round(1, { batch_id: null, verdict: null, verdict_detail: null });
  const full = { answered: 4, total: 4 };
  it.each([
    ["a new session waiting", "queued", null, 1, [], null, null],
    ["reading what went wrong", "running", "analyzing", 1, [], null, null],
    ["sorting the examples", "running", "classifying", 1, [], null, null],
    ["drafting knowledge", "running", "drafting", 1, [fresh], null, null],
    ["writing the first changes", "running", "proposing", 1, [fresh], null, null],
    [
      "asking both sides",
      "running",
      "evaluating",
      1,
      [round(1, { verdict: null })],
      null,
      { answered: 2, total: 4 },
    ],
    ["grading attempt 1", "running", "judging", 1, [round(1, { verdict: null })], null, full],
    [
      "writing attempt 2 of 3",
      "running",
      "proposing",
      2,
      [round(1), round(2, { batch_id: null, verdict: null })],
      null,
      full,
    ],
    [
      "checking attempt 2 of 3",
      "running",
      "evaluating",
      2,
      [round(1), round(2, { verdict: null })],
      null,
      full,
    ],
    ["stopped after reading what went wrong", "waiting", "classifying", 1, [], null, null],
    ["stopped with changes to review", "waiting", "filtering", 1, [fresh], null, null],
    ["a result to accept", "ready", "judging", 1, [round(1, { verdict: "better" })], null, full],
    ["only missing knowledge", "stopped", "drafting", 1, [fresh], "knowledge_only", null],
    ["nothing to learn from", "stopped", "analyzing", 1, [], "no_data", null],
    [
      "out of attempts",
      "stopped",
      "judging",
      3,
      [round(1), round(2, { verdict: "regression" }), round(3)],
      "max_iterations",
      full,
    ],
    ["a failed check", "failed", "evaluating", 1, [round(1, { verdict: null })], "eval", null],
    ["kept as a draft", "accepted", "judging", 1, [round(1, { verdict: "better" })], null, full],
  ] as const)("%s", async (_, status, stage, iteration, rounds, stop, before) => {
    state.session = {
      ...state.session!,
      status,
      stage,
      iteration,
      iterations: rounds.map((item) => ({ ...item })),
      stop_reason: stop,
      best_iteration_id: status === "ready" || status === "accepted" ? "r1" : null,
      baseline_answers: before,
    };
    render(<ImprovementPage agentId="a1" sessionId="s1" />);
    const views = improvementSteps(state.session);
    const running = STEPS.some((id) => views[id].state === "running");
    expect(
      within(screen.getByRole("region", { name: "Session" })).getByRole("status"),
    ).toHaveTextContent(running ? "Working" : /^(?!Working)/);
    for (const id of STEPS) {
      const trigger = screen.getByRole("button", { name: LABELS[id] });
      if (!isReachable(views[id])) {
        expect(trigger, id).toHaveAttribute("aria-disabled", "true");
        continue;
      }
      await userEvent.click(trigger);
      const panel = document.querySelector("[data-step-panel]")!;
      if (views[id].state === "running") {
        expect(panel.textContent, id).toMatch(WORKING);
        expect(panel.textContent, id).not.toMatch(FINAL);
      } else {
        expect(panel.textContent, id).not.toMatch(WORKING);
      }
    }
  });
});
