import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import * as runsApi from "@/lib/workflows/runs-api";
import type { WorkflowNodeRunRead, WorkflowRunRead } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import WorkflowRunPage from "./page";

/**
 * The run page's permission gates, proven against the real hooks and a mocked API: what
 * a person sees follows the run's own `can_cancel` (the server's answer to "may this
 * caller cancel and resolve"), and Retry on a test run also needs edit. A control that
 * is not shown cannot answer 403.
 */

const state = vi.hoisted(() => ({
  can: true,
  canEdit: false,
  workflowError: null as Error | null,
  catalogError: null as Error | null,
  refetchWorkflow: vi.fn(),
  refetchCatalog: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/workflows/w1/runs/r1",
}));
vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  useWorkflow: () => ({
    workflow: { id: "w1", name: "Flow", can_edit: state.canEdit },
    error: state.workflowError,
    refetch: state.refetchWorkflow,
  }),
  useNodeCatalog: () => ({
    nodes: [],
    isLoading: false,
    error: state.catalogError,
    refetch: state.refetchCatalog,
  }),
  usePermissions: () => ({ can: () => state.can }),
  useCausingRun: () => ({ causing: null, refused: false }),
}));
vi.mock("@/lib/workflows/runs-api");
vi.mock("@/lib/workflows/logs-api", () => ({
  listRunLogs: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/components/workflows/canvas", async (original) => ({
  ...(await original<typeof import("@/components/workflows/canvas")>()),
  WorkflowCanvas: () => null,
}));
vi.mock("@/components/workflows/node-editor", () => ({ NodeEditorDialog: () => null }));

const run = (patch: Partial<WorkflowRunRead>): WorkflowRunRead =>
  ({
    id: "r1",
    workflow_id: "w1",
    mode: "real",
    status: "needs_attention",
    triggered_by: "manual",
    budget_limit: null,
    spent_cost: 0,
    cost_is_partial: false,
    error: null,
    output: null,
    causation_run_id: null,
    retry_of_run_id: null,
    can_cancel: true,
    started_at: null,
    ended_at: null,
    ...patch,
  }) as WorkflowRunRead;

const step = (status: WorkflowNodeRunRead["status"]): WorkflowNodeRunRead => ({
  id: "n1",
  node_instance_id: "a",
  scope_path: [],
  status,
  waiting_reason: null,
  attempts: 1,
  cost: 0,
  error: null,
  output: null,
  last_attempt_status: null,
  late_output: null,
  started_at: null,
  ended_at: null,
});

function seed(runPatch: Partial<WorkflowRunRead>, stepStatus: WorkflowNodeRunRead["status"]) {
  vi.mocked(runsApi.getWorkflowRun).mockResolvedValue(run(runPatch));
  vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
    items: [step(stepStatus)],
    total: 1,
  });
  vi.mocked(runsApi.getWorkflowRunGraph).mockResolvedValue({
    entry_node_id: "a",
    nodes: [
      { id: "a", definition_id: "act", definition_version: 1, config: {}, layout: { x: 0, y: 0 } },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  });
  vi.mocked(runsApi.listWorkflowRunFiles).mockResolvedValue({ items: [] });
}

async function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const params = Promise.resolve({ id: "w1", runId: "r1" });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>
          <WorkflowRunPage params={params} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.can = true;
  state.canEdit = false;
  state.workflowError = null;
  state.catalogError = null;
});
afterEach(() => useWorkflowEditorStore.getState().teardown());

describe("who sees Resolve and Cancel", () => {
  it("shows both to a caller the server says may cancel, even without the run role", async () => {
    // An editor whose edit comes from a grant alone holds no `workflows:run`.
    state.can = false;
    seed({ can_cancel: true }, "needs_attention");
    await renderPage();
    expect(await screen.findByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeInTheDocument();
  });

  it("shows neither to a plain runner who is not the starter or an editor", async () => {
    state.can = true;
    seed({ can_cancel: false }, "needs_attention");
    await renderPage();
    await screen.findByRole("heading", { name: "Flow" });
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows no Resolve on a run that has ended", async () => {
    seed({ status: "failed", can_cancel: true }, "needs_attention");
    await renderPage();
    await screen.findByRole("heading", { name: "Flow" });
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });
});

describe("who sees Retry", () => {
  it("hides Retry on a test run from someone who cannot edit, and shows it to an editor", async () => {
    seed({ status: "failed", mode: "test" }, "failed");
    await renderPage();
    await screen.findByRole("heading", { name: "Flow" });
    expect(screen.queryByRole("button", { name: "Retry from failed step" })).toBeNull();
  });

  it("shows Retry on a test run to an editor", async () => {
    state.canEdit = true;
    seed({ status: "failed", mode: "test" }, "failed");
    await renderPage();
    expect(
      await screen.findByRole("button", { name: "Retry from failed step" }),
    ).toBeInTheDocument();
  });

  it("hides Retry on a cancelled run from someone who could not have cancelled it", async () => {
    seed({ status: "cancelled", mode: "real", can_cancel: false }, "failed");
    await renderPage();
    await screen.findByRole("heading", { name: "Flow" });
    expect(screen.queryByRole("button", { name: "Retry from failed step" })).toBeNull();
  });

  it("shows Retry on a cancelled run to its starter or an editor", async () => {
    seed({ status: "cancelled", mode: "real", can_cancel: true }, "failed");
    await renderPage();
    expect(
      await screen.findByRole("button", { name: "Retry from failed step" }),
    ).toBeInTheDocument();
  });

  it("keeps Retry on a real run for anyone who may run it", async () => {
    seed({ status: "failed", mode: "real" }, "failed");
    await renderPage();
    expect(
      await screen.findByRole("button", { name: "Retry from failed step" }),
    ).toBeInTheDocument();
  });
});

describe("resolving a step that was already resolved", () => {
  it("reads the run again and takes the dialog away once the step no longer needs attention", async () => {
    seed({ can_cancel: true }, "needs_attention");
    vi.mocked(runsApi.resolveWorkflowRunStep).mockRejectedValue(
      new ApiError(409, "Conflict", { error: { code: "WORKFLOW_STEP_NOT_RESOLVABLE" } }),
    );
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    // Someone else resolved it: the next read finds the step running.
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [step("running")],
      total: 1,
    });
    fireEvent.click(screen.getByRole("button", { name: "Run it again" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(runsApi.getWorkflowRun).toHaveBeenCalledTimes(2);
  });
});

describe("questions inside a workflow agent step", () => {
  it("lets the asked person answer without granting workflow cancellation or the run role", async () => {
    state.can = false;
    seed({ status: "waiting_for_user", can_cancel: false }, "waiting");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [{ ...step("waiting"), waiting_reason: "question" }],
      total: 1,
    });
    vi.mocked(runsApi.listWorkflowRunQuestions)
      .mockResolvedValueOnce([
        {
          workflow_run_id: "r1",
          node_run_id: "n1",
          agent_run_id: "agent-run",
          questions: [
            {
              tool_call_id: "clarify",
              questions: [
                { question: "Which project?", allow_custom: false, options: [{ label: "Pilot" }] },
              ],
            },
          ],
        },
      ])
      .mockResolvedValue([]);
    vi.mocked(runsApi.answerWorkflowRunQuestions).mockResolvedValue(
      run({ status: "running", can_cancel: false }),
    );
    await renderPage();
    expect(await screen.findByText("Waiting for user")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Pilot/ }));
    await waitFor(() =>
      expect(runsApi.answerWorkflowRunQuestions).toHaveBeenCalledWith("r1", "n1", {
        clarify: [{ answer: "", selected: ["Pilot"], skipped: false }],
      }),
    );
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows a nested agent question while the outer step waits for its child workflow", async () => {
    seed({ status: "running", can_cancel: false }, "waiting");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [{ ...step("waiting"), waiting_reason: "external_event" }],
      total: 1,
    });
    vi.mocked(runsApi.listWorkflowRunQuestions).mockResolvedValue([
      {
        workflow_run_id: "child",
        node_run_id: "child-step",
        agent_run_id: "child-agent",
        questions: [
          {
            tool_call_id: "clarify",
            questions: [{ question: "Which nested project?", allow_custom: true }],
          },
        ],
      },
    ]);
    await renderPage();
    expect(await screen.findByText("Which nested project?")).toBeInTheDocument();
    expect(runsApi.listWorkflowRunQuestions).toHaveBeenCalledWith("r1");
  });

  it("hides question controls from other viewers even when they may cancel the workflow", async () => {
    seed({ status: "waiting_for_user", can_cancel: true }, "waiting");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [{ ...step("waiting"), waiting_reason: "question" }],
      total: 1,
    });
    vi.mocked(runsApi.listWorkflowRunQuestions).mockResolvedValue([]);
    await renderPage();
    await waitFor(() => expect(runsApi.listWorkflowRunQuestions).toHaveBeenCalledWith("r1"));
    expect(screen.queryByText("Your agent needs an answer to continue")).toBeNull();
    expect(runsApi.answerWorkflowRunQuestions).not.toHaveBeenCalled();
  });
});

describe("the step list", () => {
  it("opens a loop step at the iteration its row ran in", async () => {
    seed({ status: "succeeded" }, "succeeded");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [0, 1].map((index) => ({
        ...step("succeeded"),
        id: `n${index}`,
        scope_path: [{ loop_node_id: "l", index }],
        output: { item: index },
      })),
      total: 2,
    });
    await renderPage();
    await screen.findByText("Iteration 1");
    const rows = await screen.findAllByRole("button", { name: /act/ });

    fireEvent.click(rows[0] as HTMLElement);

    const store = useWorkflowEditorStore.getState();
    expect(store.editingNodeId).toBe("a");
    expect(store.editingIteration).toEqual([0]);
    expect(store.iterationData["a/0"]?.output).toEqual({ item: 0 });
    expect(store.iterationData["a/1"]?.output).toEqual({ item: 1 });
    // A step test still pins the last item's data.
    expect(store.stepData["a"]?.output).toEqual({ item: 1 });
  });

  it("inspects a Python action result separately from its step and loop iteration", async () => {
    seed({ status: "succeeded" }, "succeeded");
    vi.mocked(runsApi.getWorkflowRunGraph).mockResolvedValue({
      entry_node_id: "a",
      nodes: [
        {
          id: "a",
          definition_id: "code.python.actions",
          definition_version: 1,
          layout: { x: 0, y: 0 },
          config: { actions: { lookup: { type: "workflow.run", config: { workflow_id: "wf" } } } },
        },
      ],
      scopes: [],
      edges: [],
      bindings: [],
    });
    const parent = {
      ...step("succeeded"),
      scope_path: [{ loop_node_id: "loop", index: 1 }],
      output: { result: "parent value" },
    };
    const call = {
      ...parent,
      id: "child",
      scope_path: [...parent.scope_path, { action: "lookup", index: 0 }],
      output: { text: "tool value", run_id: "child-run" },
      approval: { status: "approved" as const, decided_by_name: "Reviewer", decided_at: null },
    };
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({ items: [parent, call], total: 2 });
    await renderPage();
    fireEvent.click(await screen.findByText("Call 1: lookup"));
    expect(screen.getByText(/tool value/)).toBeVisible();
    expect(screen.getByText(/Reviewer/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      "/workflows/wf/runs/child-run",
    );
    expect(screen.getByText("1 of 1")).toBeVisible();
    expect(screen.getAllByText("Iteration 2")).toHaveLength(1);
    const store = useWorkflowEditorStore.getState();
    expect(store.iterationData["a/1"]?.output).toEqual(parent.output);
    expect(store.stepData["a"]?.output).toEqual(parent.output);
  });

  it("shows the waiting script step as running while its action runs", async () => {
    seed({}, "waiting");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [
        step("waiting"),
        { ...step("running"), id: "child", scope_path: [{ action: "lookup", index: 0 }] },
      ],
      total: 2,
    });
    await renderPage();
    expect(await screen.findByRole("button", { name: /running/i })).toBeVisible();
  });

  it("resolves the actual call, without offering a loop error route for a call outside a loop", async () => {
    seed({}, "waiting");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [
        step("waiting"),
        {
          ...step("needs_attention"),
          id: "child",
          scope_path: [{ action: "notify", index: 0 }],
        },
      ],
      total: 2,
    });
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    expect(screen.getByRole("heading", { name: /notify/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Take its error route" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Run it again" }));
    await waitFor(() =>
      expect(runsApi.resolveWorkflowRunStep).toHaveBeenCalledWith("r1", "child", "run_again"),
    );
  });

  it("leaves steps that never started out of the list and the count", async () => {
    seed({ status: "succeeded" }, "succeeded");
    vi.mocked(runsApi.listWorkflowRunNodes).mockResolvedValue({
      items: [
        step("succeeded"),
        { ...step("skipped"), id: "n2", node_instance_id: "b" },
        { ...step("pending"), id: "n3", node_instance_id: "c" },
      ],
      total: 3,
    });
    await renderPage();

    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    expect(screen.queryByText("Skipped")).toBeNull();
    expect(screen.queryByText("Pending")).toBeNull();
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
  });
});

it("offers recovery when reading the run fails instead of showing a permanent skeleton", async () => {
  seed({ status: "succeeded" }, "succeeded");
  vi.mocked(runsApi.getWorkflowRun).mockRejectedValueOnce(new Error("run unavailable"));
  await renderPage();
  expect(await screen.findByText("run unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("link", { name: "See in Logs" })).toBeVisible();
});

it.each(["listWorkflowRunNodes", "listWorkflowRunFiles", "getWorkflowRunGraph"] as const)(
  "retries a failed constituent read: %s",
  async (method) => {
    seed({ status: "succeeded" }, "succeeded");
    vi.mocked(runsApi[method]).mockRejectedValueOnce(new Error("detail unavailable"));
    await renderPage();
    expect(await screen.findByText("detail unavailable")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "See in Logs" })).toBeVisible();
  },
);

it.each(["workflow", "catalog"] as const)("retries the failed %s query owner", async (owner) => {
  seed({ status: "succeeded" }, "succeeded");
  state[owner === "workflow" ? "workflowError" : "catalogError"] = new Error("setup unavailable");
  await renderPage();
  expect(await screen.findByText("setup unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(
    owner === "workflow" ? state.refetchWorkflow : state.refetchCatalog,
  ).toHaveBeenCalledOnce();
});
