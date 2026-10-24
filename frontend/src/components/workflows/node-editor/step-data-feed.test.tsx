import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkflowNodeRunRead, WorkflowRunRead } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { StepDataFeed } from "./step-data-feed";

const runs: { runs: Partial<WorkflowRunRead>[] } = { runs: [] };
const runsById: Record<
  string,
  { run: Partial<WorkflowRunRead> | null; nodes: Partial<WorkflowNodeRunRead>[] }
> = {};
const read = vi.fn((runId: string) => runsById[runId] ?? { run: null, nodes: [] });
vi.mock("@/hooks", () => ({
  useWorkflowRuns: () => runs,
  useWorkflowRun: (runId: string) => read(runId),
}));

const store = useWorkflowEditorStore;
afterEach(() => {
  store.getState().teardown();
  runs.runs = [];
  read.mockClear();
});

function step(nodeId: string, output: Record<string, unknown>): Partial<WorkflowNodeRunRead> {
  return { node_instance_id: nodeId, status: "succeeded", output, error: null };
}

describe("StepDataFeed", () => {
  it("reads nothing while the workflow has no test run", () => {
    runs.runs = [{ id: "real", mode: "real" }];
    render(<StepDataFeed workflowId="wf" />);
    expect(read).not.toHaveBeenCalled();
  });

  it("folds in the recent test runs on opening, the newest winning", () => {
    runs.runs = [
      { id: "t1", mode: "test" },
      { id: "real", mode: "real" },
      { id: "t0", mode: "test" },
    ];
    runsById["t1"] = {
      run: { status: "running", created_at: "2026-10-24T12:01:00Z" },
      nodes: [step("a", { n: 1 })],
    };
    runsById["t0"] = {
      run: { status: "succeeded", created_at: "2026-10-24T12:00:00Z" },
      nodes: [step("a", { n: 0 }), step("b", {})],
    };
    store.getState().watchRun("t1", "a");
    render(<StepDataFeed workflowId="wf" />);

    expect(read.mock.calls.map(([id]) => id)).toEqual(["t0", "t1"]);
    expect(store.getState().stepData["a"]).toEqual({ output: { n: 1 }, error: null, runId: "t1" });
    expect(store.getState().stepData["b"]?.runId).toBe("t0");
    // An older run having ended says nothing of the step test still running.
    expect(store.getState().testingNodeId).toBe("a");
  });

  it("follows the run started from the editor, and ends the step test with it", () => {
    runs.runs = [{ id: "t1", mode: "test" }];
    runsById["t2"] = { run: { status: "succeeded" }, nodes: [] };
    store.getState().watchRun("t2", "b");
    render(<StepDataFeed workflowId="wf" />);

    expect(read.mock.calls.map(([id]) => id)).toEqual(["t1", "t2"]);
    expect(store.getState().testingNodeId).toBeNull();
  });
});

it("keeps newer step data when an older request resolves later", () => {
  runs.runs = [
    { id: "new", mode: "test" },
    { id: "old", mode: "test" },
  ];
  runsById["new"] = {
    run: { status: "running", created_at: "2026-10-24T12:01:00Z" },
    nodes: [step("a", { n: 2 })],
  };
  runsById["old"] = { run: { status: "succeeded", created_at: "2026-10-24T12:00:00Z" }, nodes: [] };
  const view = render(<StepDataFeed workflowId="wf" />);
  runsById["old"] = { ...runsById["old"]!, nodes: [step("a", { n: 1 }), step("b", { n: 0 })] };
  view.rerender(<StepDataFeed workflowId="wf" />);
  expect(store.getState().stepData["a"]?.output).toEqual({ n: 2 });
  expect(store.getState().stepData["b"]?.output).toEqual({ n: 0 });
});

it("uses run-list age for equal timestamps and still refreshes the same newest run", () => {
  runs.runs = [
    { id: "new", mode: "test" },
    { id: "old", mode: "test" },
  ];
  const at = "2026-10-24T12:00:00Z";
  runsById["new"] = { run: { status: "running", created_at: at }, nodes: [step("a", { n: 2 })] };
  runsById["old"] = { run: { status: "succeeded", created_at: at }, nodes: [] };
  const view = render(<StepDataFeed workflowId="wf" />);
  runsById["old"] = { run: { status: "succeeded", created_at: at }, nodes: [step("a", { n: 1 })] };
  view.rerender(<StepDataFeed workflowId="wf" />);
  expect(store.getState().stepData["a"]?.output).toEqual({ n: 2 });
  runsById["new"] = { run: { status: "running", created_at: at }, nodes: [step("a", { n: 3 })] };
  view.rerender(<StepDataFeed workflowId="wf" />);
  expect(store.getState().stepData["a"]?.output).toEqual({ n: 3 });
});

it("falls back to the ordered run list when stored timestamps are absent", () => {
  runs.runs = [
    { id: "new", mode: "test" },
    { id: "old", mode: "test" },
  ];
  runsById["new"] = {
    run: { status: "running", created_at: null, started_at: null },
    nodes: [step("a", { n: 2 })],
  };
  runsById["old"] = { run: { status: "succeeded", created_at: null, started_at: null }, nodes: [] };
  const view = render(<StepDataFeed workflowId="wf" />);
  runsById["old"] = { ...runsById["old"]!, nodes: [step("a", { n: 1 })] };
  view.rerender(<StepDataFeed workflowId="wf" />);
  expect(store.getState().stepData["a"]?.output).toEqual({ n: 2 });
});

it("resets example provenance when the editor changes workflow", () => {
  runs.runs = [{ id: "switch-run", mode: "test" }];
  runsById["switch-run"] = {
    run: { status: "succeeded", created_at: "2026-10-24T10:00:00Z" },
    nodes: [step("same-step", { n: 2 })],
  };
  const view = render(<StepDataFeed workflowId="first-workflow" />);
  runsById["switch-run"] = {
    run: { status: "succeeded", created_at: "2026-10-23T10:00:00Z" },
    nodes: [step("same-step", { n: 1 })],
  };
  view.rerender(<StepDataFeed workflowId="second-workflow" />);
  expect(store.getState().stepData["same-step"]?.output).toEqual({ n: 1 });
});
