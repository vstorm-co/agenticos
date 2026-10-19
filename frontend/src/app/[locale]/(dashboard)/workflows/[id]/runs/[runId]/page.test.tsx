import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  WorkflowGraph,
  WorkflowNodeRunRead,
  WorkflowRunRead,
  WorkflowRunStatus,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import WorkflowRunPage from "./page";

/**
 * The run page's `watched` latch: a run seen while it went keeps moving once it
 * ends - its failure shakes, its wires move - and a run opened after it ended is
 * drawn still. The canvas is a marker reading the overlay it is handed.
 */

const state = vi.hoisted(() => ({ status: "running" as string, step: "running" as string }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/workflows/w1/runs/r1",
}));

const GRAPH: WorkflowGraph = {
  entry_node_id: "a",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  useWorkflow: () => ({ workflow: { id: "w1", name: "Flow", can_edit: false } }),
  useNodeCatalog: () => ({ nodes: [], isLoading: false }),
  usePermissions: () => ({ can: () => false }),
  useCausingRun: () => ({ causing: null, refused: false }),
  useWorkflowRun: () => ({
    run: {
      id: "r1",
      mode: "test",
      status: state.status as WorkflowRunStatus,
      triggered_by: "manual",
      budget_limit: null,
      spent_cost: 0,
      cost_is_partial: false,
      error: null,
      output: null,
      causation_run_id: null,
      retry_of_run_id: null,
      started_at: null,
      ended_at: null,
    } as Partial<WorkflowRunRead>,
    isLoading: false,
    nodes: [
      {
        id: "n1",
        node_instance_id: "a",
        scope_path: [],
        status: state.step,
        waiting_reason: null,
        attempts: 1,
        cost: 0,
        error: null,
        output: null,
        started_at: null,
        ended_at: null,
      } as WorkflowNodeRunRead,
    ],
    files: [],
    graph: GRAPH,
    cancel: { mutate: vi.fn(), isPending: false },
    retry: { mutate: vi.fn(), isPending: false },
  }),
}));

vi.mock("@/components/workflows/canvas", async (original) => {
  const actual = await original<typeof import("@/components/workflows/canvas")>();
  const { useNodeRunState } = await import("@/components/workflows/canvas/run-overlay");
  function Marker() {
    const look = useNodeRunState("a");
    return <span>{`a:${look?.state}:${look?.watched ? "watched" : "still"}`}</span>;
  }
  return { ...actual, WorkflowCanvas: Marker };
});
vi.mock("@/components/workflows/node-editor", () => ({ NodeEditorDialog: () => null }));

afterEach(() => {
  useWorkflowEditorStore.getState().teardown();
  state.status = "running";
  state.step = "running";
});

const params = Promise.resolve({ id: "w1", runId: "r1" });
const page = () => (
  <Suspense fallback={null}>
    <WorkflowRunPage params={params} />
  </Suspense>
);
// The page reads its params with `use()`: the first render suspends until they resolve.
async function renderPage() {
  let rendered: ReturnType<typeof render> | undefined;
  await act(async () => {
    rendered = render(page());
  });
  return rendered as ReturnType<typeof render>;
}

describe("a run's page", () => {
  it("keeps a run it watched moving once it has ended", async () => {
    const { rerender } = await renderPage();
    expect(screen.getByText("a:running:watched")).toBeInTheDocument();

    state.status = "failed";
    state.step = "failed";
    rerender(page());
    expect(screen.getByText("a:failed:watched")).toBeInTheDocument();
  });

  it("draws a run opened after it ended still", async () => {
    state.status = "failed";
    state.step = "failed";
    await renderPage();
    expect(screen.getByText("a:failed:still")).toBeInTheDocument();
  });
});
