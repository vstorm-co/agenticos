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

const state = vi.hoisted(() => ({ can: true, canEdit: false }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/workflows/w1/runs/r1",
}));
vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  useWorkflow: () => ({ workflow: { id: "w1", name: "Flow", can_edit: state.canEdit } }),
  useNodeCatalog: () => ({ nodes: [], isLoading: false }),
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
    await screen.findByText("Flow");
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows no Resolve on a run that has ended", async () => {
    seed({ status: "failed", can_cancel: true }, "needs_attention");
    await renderPage();
    await screen.findByText("Flow");
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });
});

describe("who sees Retry", () => {
  it("hides Retry on a test run from someone who cannot edit, and shows it to an editor", async () => {
    seed({ status: "failed", mode: "test" }, "failed");
    await renderPage();
    await screen.findByText("Flow");
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
