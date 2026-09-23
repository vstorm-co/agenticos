import { beforeEach, describe, expect, it } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "./workflow-editor-store";

const INITIAL = useWorkflowEditorStore.getState();

function reset() {
  useWorkflowEditorStore.setState(
    {
      workflowId: null,
      generation: 0,
      expectedRevision: null,
      isDirty: false,
      scopePath: [],
      selection: { nodeIds: [], edgeIds: [] },
      clipboard: null,
      history: { canUndo: false, canRedo: false },
      conflict: null,
    },
    // Keep the actions, replace only the data slices.
    false,
  );
}

const NODE: NodeInstance = {
  id: "11111111-1111-1111-1111-111111111111",
  definition_id: "debug.echo",
  definition_version: 1,
  config: {},
  layout: { x: 0, y: 0 },
};

describe("useWorkflowEditorStore", () => {
  beforeEach(reset);

  it("exposes its actions on the initial state", () => {
    expect(typeof INITIAL.load).toBe("function");
    expect(INITIAL.workflowId).toBeNull();
  });

  it("load resets ephemeral slices, sets the workflow and bumps the generation", () => {
    const store = useWorkflowEditorStore;
    store.getState().markDirty();
    store.getState().enterScope("scope-1");
    store.getState().setConflict(7);

    store.getState().load({ workflowId: "wf-1", expectedRevision: 3 });

    const state = store.getState();
    expect(state.workflowId).toBe("wf-1");
    expect(state.expectedRevision).toBe(3);
    expect(state.generation).toBe(1);
    expect(state.isDirty).toBe(false);
    expect(state.scopePath).toEqual([]);
    expect(state.conflict).toBeNull();
  });

  it("teardown clears the workflow and bumps the generation again", () => {
    const store = useWorkflowEditorStore;
    store.getState().load({ workflowId: "wf-1", expectedRevision: 3 });
    store.getState().markDirty();

    store.getState().teardown();

    const state = store.getState();
    expect(state.workflowId).toBeNull();
    expect(state.expectedRevision).toBeNull();
    expect(state.generation).toBe(2);
    expect(state.isDirty).toBe(false);
  });

  it("tracks the canvas selection and clears it", () => {
    const store = useWorkflowEditorStore;
    store.getState().setSelection({ nodeIds: ["n1"], edgeIds: ["e1"] });
    expect(store.getState().selection).toEqual({ nodeIds: ["n1"], edgeIds: ["e1"] });

    store.getState().clearSelection();
    expect(store.getState().selection).toEqual({ nodeIds: [], edgeIds: [] });
  });

  it("pushes and pops the foreach scope path", () => {
    const store = useWorkflowEditorStore;
    store.getState().enterScope("a");
    store.getState().enterScope("b");
    expect(store.getState().scopePath).toEqual(["a", "b"]);

    store.getState().exitScope();
    expect(store.getState().scopePath).toEqual(["a"]);

    store.getState().setScopePath(["x", "y", "z"]);
    expect(store.getState().scopePath).toEqual(["x", "y", "z"]);
  });

  it("holds a clipboard and history flags for the leaf branches", () => {
    const store = useWorkflowEditorStore;
    const clipboard = { nodes: [NODE], edges: [], scopes: [] };
    store.getState().setClipboard(clipboard);
    expect(store.getState().clipboard).toBe(clipboard);

    store.getState().setClipboard(null);
    expect(store.getState().clipboard).toBeNull();

    store.getState().setHistoryFlags({ canUndo: true, canRedo: false });
    expect(store.getState().history).toEqual({ canUndo: true, canRedo: false });
  });

  it("moves through the dirty / saved lifecycle", () => {
    const store = useWorkflowEditorStore;
    store.getState().markDirty();
    expect(store.getState().isDirty).toBe(true);

    store.getState().setConflict(5);
    store.getState().markSaved(9);
    const state = store.getState();
    expect(state.isDirty).toBe(false);
    expect(state.expectedRevision).toBe(9);
    expect(state.conflict).toBeNull();

    store.getState().setExpectedRevision(12);
    expect(store.getState().expectedRevision).toBe(12);
  });

  it("sets and clears the conflict banner", () => {
    const store = useWorkflowEditorStore;
    store.getState().setConflict(4);
    expect(store.getState().conflict).toEqual({ currentRevision: 4 });

    store.getState().clearConflict();
    expect(store.getState().conflict).toBeNull();
  });

  it("guards a save against a stale generation or a workflow switch", () => {
    const store = useWorkflowEditorStore;
    store.getState().load({ workflowId: "wf-1", expectedRevision: 1 });

    const token = store.getState().beginSave();
    expect(token).toEqual({ generation: 1, workflowId: "wf-1" });
    expect(store.getState().isSaveCurrent(token)).toBe(true);

    // A remount (another load) bumps the generation, so the captured token is stale.
    store.getState().load({ workflowId: "wf-1", expectedRevision: 1 });
    expect(store.getState().isSaveCurrent(token)).toBe(false);

    // A switch to a different workflow also invalidates a same-generation token.
    const other = store.getState().beginSave();
    store.setState({ workflowId: "wf-2" });
    expect(store.getState().isSaveCurrent(other)).toBe(false);
  });
});
