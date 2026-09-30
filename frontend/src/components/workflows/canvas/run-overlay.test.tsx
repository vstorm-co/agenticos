import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowNodeRunRead } from "@/lib/workflows/types";

import {
  NodeRunOverlayProvider,
  summarizeNodeRuns,
  useIsRunView,
  useNodeRunSummary,
} from "./run-overlay";

function row(overrides: Partial<WorkflowNodeRunRead>): WorkflowNodeRunRead {
  return {
    id: crypto.randomUUID(),
    node_instance_id: "A",
    scope_path: [],
    status: "succeeded",
    waiting_reason: null,
    attempts: 1,
    cost: 0,
    error: null,
    output: null,
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

describe("summarizeNodeRuns", () => {
  it("folds a node's iterations into the status a reader has to see first", () => {
    const summary = summarizeNodeRuns([
      row({ status: "succeeded" }),
      row({ status: "failed", attempts: 3, error: { code: "BAD", message: "m" } }),
      row({ status: "skipped" }),
      row({ node_instance_id: "B", status: "running" }),
    ]);
    expect(summary.get("A")).toEqual({
      status: "failed",
      runs: 3,
      succeeded: 1,
      attempts: 5,
      problem: { code: "BAD", message: "m" },
    });
    expect(summary.get("B")?.status).toBe("running");
  });
});

function Probe({ nodeId }: { nodeId: string }) {
  const summary = useNodeRunSummary(nodeId);
  return <span>{`${useIsRunView()}:${summary?.status ?? "none"}`}</span>;
}

describe("the overlay context", () => {
  it("is absent on the editor's canvas", () => {
    render(<Probe nodeId="A" />);
    expect(screen.getByText("false:none")).toBeTruthy();
  });

  it("answers each node's summary on a run's canvas", () => {
    render(
      <NodeRunOverlayProvider value={summarizeNodeRuns([row({})])}>
        <Probe nodeId="A" />
        <Probe nodeId="Z" />
      </NodeRunOverlayProvider>,
    );
    expect(screen.getByText("true:succeeded")).toBeTruthy();
    expect(screen.getByText("true:none")).toBeTruthy();
  });
});
