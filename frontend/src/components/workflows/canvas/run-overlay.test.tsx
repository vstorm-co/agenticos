import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowNodeRunRead } from "@/lib/workflows/types";

import {
  NodeRunOverlayProvider,
  type NodeRunSummary,
  listSize,
  nodeRunState,
  summarizeNodeRuns,
  useIsRunView,
  useNodeRunState,
  useNodeRunSummary,
  useWireRunState,
  wireRunState,
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
      items: null,
      durationMs: null,
      startedAt: null,
    });
    expect(summary.get("B")?.status).toBe("running");
  });

  it("adds up the items each row handed on, while every row handed on a list", () => {
    const summary = summarizeNodeRuns([
      row({ output: { items: [1, 2] } }),
      row({ output: { items: [3] } }),
      row({ node_instance_id: "B", output: { items: [1] } }),
      row({ node_instance_id: "B", output: { text: "no list" } }),
    ]);
    expect(summary.get("A")?.items).toBe(3);
    expect(summary.get("B")?.items).toBeNull();
  });
});

describe("listSize", () => {
  it("is the length of the one list in an output, and null otherwise", () => {
    expect(listSize({ records: [1, 2, 3], total: 3 })).toBe(3);
    expect(listSize({ a: [1], b: [2] })).toBeNull();
    expect(listSize({ text: "x" })).toBeNull();
    expect(listSize(null)).toBeNull();
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
      <NodeRunOverlayProvider
        value={{ summaries: summarizeNodeRuns([row({})]), live: false, watched: false }}
      >
        <Probe nodeId="A" />
        <Probe nodeId="Z" />
      </NodeRunOverlayProvider>,
    );
    expect(screen.getByText("true:succeeded")).toBeTruthy();
    expect(screen.getByText("true:none")).toBeTruthy();
  });
});

describe("a step's state on a run's canvas", () => {
  const summary = (status: NodeRunSummary["status"]) => ({ status }) as unknown as NodeRunSummary;

  it("reads a step not reached yet as pending, one handed its work as under way", () => {
    expect(nodeRunState(null, true)).toBe("pending");
    expect(nodeRunState(null, false)).toBe("notReached");
    // Reached, and only waiting for the engine to pick it up: under way.
    expect(nodeRunState(summary("pending"), true)).toBe("starting");
    expect(nodeRunState(summary("pending"), false)).toBe("notReached");
  });

  it("names every other status by how it reads", () => {
    expect(
      (
        [
          "running",
          "waiting",
          "succeeded",
          "failed",
          "needs_attention",
          "skipped",
          "cancelled",
        ] as const
      ).map((status) => nodeRunState(summary(status), true)),
    ).toEqual(["running", "waiting", "done", "failed", "attention", "skipped", "notReached"]);
  });

  it("draws a wire by the step it leads into, once the step before has done its part", () => {
    expect(wireRunState("done", "running")).toBe("running");
    expect(wireRunState("done", "starting")).toBe("running");
    expect(wireRunState("done", "done")).toBe("done");
    expect(wireRunState("done", "waiting")).toBe("done");
    expect(wireRunState("done", "pending")).toBe("pending");
    expect(wireRunState("done", "failed")).toBe("failed");
    expect(wireRunState("done", "attention")).toBe("failed");
    expect(wireRunState("running", "pending")).toBe("pending");
    // Down a branch the run never took, or past where it stopped.
    expect(wireRunState("done", "skipped")).toBe("faded");
    expect(wireRunState("failed", "notReached")).toBe("faded");
    expect(wireRunState("skipped", "skipped")).toBe("faded");
  });

  it("follows the step a failure was routed to, and fades where it was never reached", () => {
    // A step whose policy routes its error ends failed and hands on through its error port.
    expect(wireRunState("failed", "starting")).toBe("running");
    expect(wireRunState("failed", "running")).toBe("running");
    expect(wireRunState("failed", "done")).toBe("done");
    expect(wireRunState("failed", "failed")).toBe("failed");
    // Not reached yet while the run goes on; never reached once it ended.
    expect(wireRunState("failed", "pending")).toBe("pending");
    expect(wireRunState("failed", "notReached")).toBe("faded");
  });

  it("keeps when the row running now started, for its timer", () => {
    const start = "2026-10-19T10:00:00Z";
    expect(
      summarizeNodeRuns([row({ status: "running", started_at: start })]).get("A")?.startedAt,
    ).toBe(start);
    const loop = summarizeNodeRuns([row({}), row({ status: "running", started_at: start })]);
    expect(loop.get("A")?.startedAt).toBe(start);
    expect(summarizeNodeRuns([row({ started_at: start })]).get("A")?.startedAt).toBeNull();
  });

  it("sums how long a step's rows took", () => {
    const timed = (start: string, end: string | null) =>
      row({
        started_at: `2026-10-19T10:00:${start}Z`,
        ended_at: end && `2026-10-19T10:00:${end}Z`,
      });
    expect(summarizeNodeRuns([timed("00", "02")]).get("A")?.durationMs).toBe(2000);
    expect(summarizeNodeRuns([timed("00", "02"), timed("05", "06")]).get("A")?.durationMs).toBe(
      3000,
    );
    expect(summarizeNodeRuns([timed("00", null)]).get("A")?.durationMs).toBeNull();
    // Rows with no ends add up to unknown, not to nothing.
    expect(
      summarizeNodeRuns([timed("00", null), timed("01", null)]).get("A")?.durationMs,
    ).toBeNull();
    expect(summarizeNodeRuns([timed("00", null), timed("01", "03")]).get("A")?.durationMs).toBe(
      2000,
    );
    const later = summarizeNodeRuns([timed("00", "02"), timed("05", null)]);
    expect(later.get("A")?.durationMs).toBe(2000);
  });

  it("answers a step's and a wire's state only on a run's canvas", () => {
    function States() {
      const step = useNodeRunState("A");
      const wire = useWireRunState("A", "Z");
      return <span>{`${step?.state ?? "none"}:${wire ?? "none"}:${step?.watched ?? "-"}`}</span>;
    }
    const { unmount } = render(<States />);
    expect(screen.getByText("none:none:-")).toBeTruthy();
    unmount();
    render(
      <NodeRunOverlayProvider
        value={{ summaries: summarizeNodeRuns([row({})]), live: true, watched: true }}
      >
        <States />
      </NodeRunOverlayProvider>,
    );
    expect(screen.getByText("done:pending:true")).toBeTruthy();
  });
});
