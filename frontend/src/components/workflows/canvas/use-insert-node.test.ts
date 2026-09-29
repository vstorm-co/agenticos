import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useInsertNode } from "./use-insert-node";

const STEP = makeDefinition({
  id: "step",
  ports: [port("in", "input", null), port("out", "output", null)],
});

beforeEach(() => useWorkflowEditorStore.getState().teardown());

it("adds nothing before a draft is loaded, and plans the step once one is", () => {
  const insertNode = vi.fn();
  useWorkflowEditorStore.setState({ insertNode });
  const { result } = renderHook(() => useInsertNode([STEP]));

  result.current(STEP);
  expect(insertNode).not.toHaveBeenCalled();

  useWorkflowEditorStore.setState({
    graph: { entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] },
  });
  result.current(STEP, { dropAt: { x: 7, y: 8 } });
  expect(insertNode).toHaveBeenCalledWith(
    expect.objectContaining({ node: expect.objectContaining({ layout: { x: 7, y: 8 } }) }),
  );
});
