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

const state = vi.hoisted(() => ({
  status: "running" as string,
  mode: "test" as string,
  step: "running" as string,
  logs: [] as unknown[],
  logsError: null as Error | null,
  twice: false,
  graphNodes: null as unknown,
  catalog: [] as unknown[],
}));

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
  useNodeCatalog: () => ({ nodes: state.catalog, isLoading: false }),
  usePermissions: () => ({ can: () => false }),
  useCausingRun: () => ({ causing: null, refused: false }),
  useWorkflowRun: () => ({
    run: {
      id: "r1",
      mode: state.mode,
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
    nodes: (state.twice ? ["n1", "n2"] : ["n1"]).map(
      (id) =>
        ({
          id,
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
        }) as WorkflowNodeRunRead,
    ),
    files: [],
    logs: state.logs,
    logsError: state.logsError,
    graph: state.graphNodes === null ? GRAPH : (state.graphNodes as WorkflowGraph),
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
  state.mode = "test";
  state.status = "running";
  state.step = "running";
  state.logs = [];
  state.logsError = null;
  state.twice = false;
  state.graphNodes = null;
  state.catalog = [];
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
  it("links to the Logs page filtered to this run, showing test lines for a test run", async () => {
    await renderPage();
    expect(screen.getByRole("link", { name: "See in Logs" })).toHaveAttribute(
      "href",
      "/workflows/w1/logs?run=r1&test=1",
    );
  });

  it("leaves test lines out of the link for a real run", async () => {
    state.mode = "real";
    await renderPage();
    expect(screen.getByRole("link", { name: "See in Logs" })).toHaveAttribute(
      "href",
      "/workflows/w1/logs?run=r1",
    );
  });

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

  it("lists what a step's quick log wrote under that step, and nothing under another", async () => {
    state.logs = [
      {
        id: "l1",
        node_instance_id: "a",
        outcome: "error",
        message: "Fetch failed: timeout",
        created_at: "2026-10-28T09:00:00Z",
        is_test: true,
        is_pinned: false,
      },
      {
        id: "l2",
        node_instance_id: "other",
        outcome: "out",
        message: "Another step's line",
        created_at: "2026-10-28T09:00:01Z",
        is_test: false,
        is_pinned: false,
      },
    ];
    await renderPage();

    const lines = screen.getAllByTestId("step-logs");
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveTextContent("Fetch failed: timeout");
    expect(lines[0]).toHaveTextContent("error");
    expect(screen.queryByText("Another step's line")).toBeNull();
  });

  it("draws no list for a step that wrote nothing", async () => {
    await renderPage();
    expect(screen.queryByTestId("step-logs")).toBeNull();
  });

  it("says so when the lines could not be read, rather than that nothing was written", async () => {
    state.logsError = new Error("boom");
    await renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByTestId("step-logs")).toBeNull();
  });

  it("lists a looping step's lines once, under its first row", async () => {
    state.twice = true;
    state.logs = [
      {
        id: "l1",
        node_instance_id: "a",
        outcome: "out",
        message: "Once only",
        created_at: "2026-10-28T09:00:00Z",
        is_test: false,
        is_pinned: false,
      },
    ];
    await renderPage();
    expect(screen.getAllByTestId("step-logs")).toHaveLength(1);
    expect(screen.getAllByText("Once only")).toHaveLength(1);
  });

  it("reads an outcome as its port's label, with seconds in the time", async () => {
    state.graphNodes = {
      ...GRAPH,
      nodes: [{ id: "a", definition_id: "http.request", definition_version: 1, config: {} }],
    };
    state.catalog = [
      {
        id: "http.request",
        version: 1,
        name: "HTTP",
        ports: [
          { id: "in", label: "in", kind: "input", schema: null },
          { id: "out", label: "Done", kind: "output", schema: null },
        ],
      },
    ];
    state.logs = [
      {
        id: "l1",
        node_instance_id: "a",
        outcome: "out",
        message: "Fetched",
        created_at: "2026-10-28T09:00:07Z",
        is_test: false,
        is_pinned: false,
      },
    ];
    await renderPage();
    const lines = screen.getByTestId("step-logs");
    expect(lines).toHaveTextContent("Done");
    expect(lines).toHaveTextContent(/:07/);
  });
});
