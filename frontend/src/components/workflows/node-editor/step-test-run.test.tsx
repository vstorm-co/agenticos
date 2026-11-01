import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeRunStatus, WorkflowNodeRunRead, WorkflowRunRead } from "@/lib/workflows/types";

import { StepTestRun } from "./step-test-run";

const state = vi.hoisted(() => ({
  run: null as Partial<WorkflowRunRead> | null,
  nodes: [] as Partial<WorkflowNodeRunRead>[],
  cancel: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/hooks", () => ({
  useWorkflowRun: () => ({ run: state.run, nodes: state.nodes, cancel: state.cancel }),
}));

const nodeRun = (
  status: NodeRunStatus,
  scope: WorkflowNodeRunRead["scope_path"] = [],
): Partial<WorkflowNodeRunRead> => ({ node_instance_id: "n", scope_path: scope, status });

beforeEach(() => {
  state.run = null;
  state.nodes = [];
  state.cancel = { mutate: vi.fn(), isPending: false };
});

describe("StepTestRun", () => {
  it("offers Stop while the test runs, and stops it", async () => {
    state.run = { status: "running" };
    render(<StepTestRun runId="r" nodeId="n" />);
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(state.cancel.mutate).toHaveBeenCalledOnce();
  });

  it("cannot be pressed twice while the stop is on its way", () => {
    state.run = { status: "running" };
    state.cancel.isPending = true;
    render(<StepTestRun runId="r" nodeId="n" />);
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
  });

  it("says nothing before the run is read, or once the step ran or failed", () => {
    const { rerender } = render(<StepTestRun runId="r" nodeId="n" />);
    expect(screen.queryByRole("button")).toBeNull();
    for (const status of ["succeeded", "failed"]) {
      state.run = { status: "succeeded" };
      state.nodes = [nodeRun(status as NodeRunStatus)];
      rerender(<StepTestRun runId="r" nodeId="n" />);
      expect(screen.queryByRole("button")).toBeNull();
    }
  });

  it.each([
    ["skipped on another branch", "succeeded", [nodeRun("skipped")], /went down another branch/],
    ["never reached", "failed", [], /ended before reaching it/],
    [
      "reached only inside a loop",
      "succeeded",
      [nodeRun("succeeded", [{ loop_node_id: "loop", index: 0 }])],
      /ended before/,
    ],
    ["stopped", "cancelled", [nodeRun("pending")], /was stopped/],
  ])("warns when the step did not run: %s", (_case, runStatus, nodes, reason) => {
    state.run = { status: runStatus as WorkflowRunRead["status"] };
    state.nodes = nodes;
    render(<StepTestRun runId="r" nodeId="n" />);
    expect(screen.getByRole("button", { name: reason })).toBeInTheDocument();
  });
});
