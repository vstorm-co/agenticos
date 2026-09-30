import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { makeDefinition } from "@/components/workflows/validation/fixtures";
import type { WorkflowNodeRunRead } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { DebugRun } from "./debug-run";

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));
const read = vi.hoisted(() => ({ nodes: [] as Partial<WorkflowNodeRunRead>[] }));
vi.mock("@/hooks", () => ({
  useWorkflowRun: () => ({ run: { id: "r" }, nodes: read.nodes }),
}));

const store = useWorkflowEditorStore;
const node = (id: string, definitionId = "test.step") => ({
  id,
  definition_id: definitionId,
  definition_version: 1,
  config: {},
  layout: { x: 0, y: 0 },
});
const catalog = [
  makeDefinition({ id: "test.step" }),
  makeDefinition({ id: "logic.if", kind: "control" }),
];

afterEach(() => store.getState().teardown());

describe("DebugRun", () => {
  it("pins what each top-level step of the draft handed on in the run, once", () => {
    store.getState().seedGraph({
      entry_node_id: "a",
      nodes: [node("a"), node("b", "logic.if"), node("c"), node("d")],
      edges: [],
      bindings: [],
      scopes: [],
    });
    read.nodes = [
      { node_instance_id: "a", scope_path: [], status: "succeeded", output: { x: 1 }, error: null },
      { node_instance_id: "b", scope_path: [], status: "succeeded", output: { y: 1 }, error: null },
      {
        node_instance_id: "c",
        scope_path: [{ loop_node_id: "l", index: 0 }],
        status: "succeeded",
        output: { z: 1 },
        error: null,
      },
      { node_instance_id: "d", scope_path: [], status: "failed", output: null, error: null },
      { node_instance_id: "gone", scope_path: [], status: "succeeded", output: {}, error: null },
    ];
    const onDone = vi.fn();
    const { rerender } = render(<DebugRun runId="r" catalog={catalog} onDone={onDone} />);
    rerender(<DebugRun runId="r" catalog={catalog} onDone={onDone} />);

    const pinned = store.getState().graph?.nodes.map((item) => item.pinned_output);
    expect(pinned).toEqual([{ x: 1 }, undefined, undefined, undefined]);
    expect(store.getState().stepData["a"]?.output).toEqual({ x: 1 });
    expect(toast.success).toHaveBeenCalledWith("Pinned 1 step's data from the run");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("waits for the draft and the run, and pins nothing when nothing fits", () => {
    read.nodes = [];
    const onDone = vi.fn();
    const { rerender } = render(<DebugRun runId="r" catalog={catalog} onDone={onDone} />);
    expect(onDone).not.toHaveBeenCalled();

    store
      .getState()
      .seedGraph({ entry_node_id: "a", nodes: [node("a")], edges: [], bindings: [], scopes: [] });
    read.nodes = [
      { node_instance_id: "a", scope_path: [], status: "failed", output: null, error: null },
    ];
    rerender(<DebugRun runId="r" catalog={catalog} onDone={onDone} />);
    expect(store.getState().isDirty).toBe(false);
    expect(toast.success).toHaveBeenLastCalledWith("Nothing to pin from this run");
  });
});
