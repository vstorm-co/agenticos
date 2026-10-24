import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Improvement } from "@/types/improvement";
import { ImprovementPage } from "./improvement-page";
import { hunk } from "@/test-utils/authoring";
import type { Hunk } from "@/types/authoring";
const actions = vi.hoisted(() => ({
  cancel: { mutateAsync: vi.fn(), isPending: false },
  retry: { mutateAsync: vi.fn(), isPending: false },
  selectRound: { mutateAsync: vi.fn(), isPending: false },
  finish: { mutateAsync: vi.fn(), isPending: false },
  estimateAttribution: { mutateAsync: vi.fn(), isPending: false },
  attribute: { mutateAsync: vi.fn(), isPending: false },
}));
const state = vi.hoisted(() => ({
  edit: true,
  runs: true,
  publish: true,
  session: null as Improvement | null,
  hunks: [] as Hunk[],
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgent: () => ({
    agent: { id: "a1", name: "Refund desk", can_edit: state.edit, can_publish: state.publish },
  }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.runs }) }));
vi.mock("@/hooks/use-authoring", () => ({
  useAgentAuthoring: () => ({ authoring: { batch: { id: "b1", hunks: state.hunks } } }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    ...actions,
    session: state.session,
    error: null,
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("./knowledge-drafts", () => ({ KnowledgeDrafts: () => null }));
vi.mock("./start-session", () => ({ StartSession: () => <p>Start fixture</p> }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({ run: null, error: null }),
  useEvalComparison: () => ({ comparison: null }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.edit = true;
  state.runs = true;
  state.publish = true;
  state.hunks = [];
  state.session = {
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
  expect(actions.retry.mutateAsync).toHaveBeenCalled();
});
