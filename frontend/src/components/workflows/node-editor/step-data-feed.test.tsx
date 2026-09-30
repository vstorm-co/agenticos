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

  it("folds in the latest test run's steps on opening", () => {
    runs.runs = [
      { id: "real", mode: "real" },
      { id: "t1", mode: "test" },
    ];
    runsById["t1"] = { run: { status: "running" }, nodes: [step("a", { n: 1 })] };
    render(<StepDataFeed workflowId="wf" />);

    expect(read).toHaveBeenCalledWith("t1");
    expect(store.getState().stepData["a"]).toEqual({ output: { n: 1 }, error: null, runId: "t1" });
  });

  it("follows the run started from the editor, and ends the step test with it", () => {
    runs.runs = [{ id: "t1", mode: "test" }];
    runsById["t2"] = { run: { status: "succeeded" }, nodes: [] };
    store.getState().watchRun("t2", "b");
    render(<StepDataFeed workflowId="wf" />);

    expect(read).toHaveBeenLastCalledWith("t2");
    expect(store.getState().testingNodeId).toBeNull();
    expect(store.getState().stepData).toEqual({});
  });
});
