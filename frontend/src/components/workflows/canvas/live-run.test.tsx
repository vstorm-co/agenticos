import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { LiveRun, LiveRunStop, StaleRun } from "./live-run";
import { useNodeRunState, useNodeRunSummary } from "./run-overlay";

const watched = vi.hoisted(() => ({
  status: "running",
  cancel: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/hooks", () => ({
  useWorkflowRun: () => ({
    run: { id: "run-1", status: watched.status },
    nodes: [
      { node_instance_id: "a", status: "succeeded", attempts: 1, error: null },
      { node_instance_id: "b", status: "running", attempts: 1, error: null },
    ],
    cancel: watched.cancel,
  }),
}));

const store = useWorkflowEditorStore;
afterEach(() => store.getState().teardown());

function Card({ id }: { id: string }) {
  return <span>{`${id}:${useNodeRunSummary(id)?.status ?? "none"}`}</span>;
}

describe("LiveRun", () => {
  it("gives each step its run's status, says how the run stands, and ends on an edit", async () => {
    store
      .getState()
      .seedGraph({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] });
    const onClose = vi.fn();
    const onStale = vi.fn();
    render(
      <LiveRun workflowId="wf" runId="run-1" onClose={onClose} onStale={onStale}>
        <Card id="a" />
        <Card id="b" />
      </LiveRun>,
    );
    expect(screen.getByText("a:succeeded")).toBeTruthy();
    expect(screen.getByText("b:running")).toBeTruthy();
    expect(screen.getByText("1 step done")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open run/ }).getAttribute("href")).toBe(
      "/workflows/wf/runs/run-1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Hide the run" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => {
      store
        .getState()
        .seedGraph({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] });
    });
    expect(onStale).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

/** How a step reads under the overlay: its state, and whether it moves. */
function Look({ id }: { id: string }) {
  const look = useNodeRunState(id);
  return <span>{`${id}:${look?.state}:${look?.watched ? "watched" : "still"}`}</span>;
}

describe("LiveRun's overlay", () => {
  it("is watched as it goes, and fades a step the run ended without reaching", () => {
    store
      .getState()
      .seedGraph({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] });
    const props = { workflowId: "wf", runId: "run-1", onClose: vi.fn(), onStale: vi.fn() };
    const { rerender } = render(
      <LiveRun {...props}>
        <Look id="b" />
        <Look id="c" />
      </LiveRun>,
    );
    // Started from the editor: a failure shakes, the step running glows.
    expect(screen.getByText("b:running:watched")).toBeTruthy();
    expect(screen.getByText("c:pending:watched")).toBeTruthy();

    watched.status = "failed";
    rerender(
      <LiveRun {...props}>
        <Look id="b" />
        <Look id="c" />
      </LiveRun>,
    );
    expect(screen.getByText("c:notReached:watched")).toBeTruthy();
    watched.status = "running";
  });
});

describe("StaleRun", () => {
  it("says the graph changed since, links the run's page, and closes", async () => {
    const onClose = vi.fn();
    render(<StaleRun workflowId="wf" runId="run-1" onClose={onClose} />);

    expect(screen.getByText("The graph changed since the last test run.")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open run/ }).getAttribute("href")).toBe(
      "/workflows/wf/runs/run-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Hide the run" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("LiveRunStop", () => {
  it("stops the run Run started while it goes, and is gone once it ended", async () => {
    watched.status = "running";
    const { unmount } = render(<LiveRunStop runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    expect(watched.cancel.mutate).toHaveBeenCalledOnce();
    unmount();

    watched.status = "succeeded";
    render(<LiveRunStop runId="run-1" />);
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    watched.status = "running";
  });
});
