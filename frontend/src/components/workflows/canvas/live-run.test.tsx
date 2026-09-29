import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { LiveRun } from "./live-run";
import { useNodeRunSummary } from "./run-overlay";

vi.mock("@/hooks", () => ({
  useWorkflowRun: () => ({
    run: { id: "run-1", status: "running" },
    nodes: [
      { node_instance_id: "a", status: "succeeded", attempts: 1, error: null },
      { node_instance_id: "b", status: "running", attempts: 1, error: null },
    ],
  }),
}));

const store = useWorkflowEditorStore;
afterEach(() => store.getState().teardown());

function Card({ id }: { id: string }) {
  return <span>{`${id}:${useNodeRunSummary(id)?.status ?? "none"}`}</span>;
}

describe("LiveRun", () => {
  it("gives each step its run's status, says how the run stands, and closes on an edit", async () => {
    store
      .getState()
      .seedGraph({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] });
    const onClose = vi.fn();
    render(
      <LiveRun workflowId="wf" runId="run-1" onClose={onClose}>
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
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
