import { beforeEach, describe, expect, it } from "vitest";

import type {
  Binding,
  NodeDefinition,
  NodeInstance,
  ScopeBoundary,
  WorkflowGraph,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "./workflow-editor-store";

const INITIAL = useWorkflowEditorStore.getState();

function reset() {
  useWorkflowEditorStore.setState(
    {
      workflowId: null,
      generation: 0,
      expectedRevision: null,
      isDirty: false,
      graph: null,
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

/** A node with an explicit id and layout, for graph-slice fixtures. */
function nodeAt(id: string, x: number, y: number): NodeInstance {
  return { id, definition_id: "debug.echo", definition_version: 1, config: {}, layout: { x, y } };
}

/** A two-node graph with one edge and `a` as entry — a minimal editable draft. */
function seededGraph(): WorkflowGraph {
  return {
    entry_node_id: "a",
    nodes: [nodeAt("a", 0, 0), nodeAt("b", 100, 0)],
    edges: [
      { id: "e1", source_node_id: "a", source_port: "out", target_node_id: "b", target_port: "in" },
    ],
    bindings: [],
    scopes: [],
  };
}

const DEFINITION: NodeDefinition = {
  id: "debug.echo",
  version: 1,
  name: "Echo",
  category: "debug",
  description: "",
  kind: "action",
  config_schema: null,
  input_schema: null,
  output_schema: null,
  ports: [],
  effect_kind: "pure",
  retry_guarantee: "none",
  scopes: [],
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
    const clipboard = { nodes: [NODE], edges: [], bindings: [], scopes: [] };
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

describe("useWorkflowEditorStore graph slice", () => {
  const store = useWorkflowEditorStore;

  beforeEach(() => {
    reset();
    // Null the module-level history recorder that a prior test's `seedGraph` set.
    store.getState().teardown();
    reset();
  });

  it("seedGraph installs the working graph without marking it dirty", () => {
    store.getState().seedGraph(seededGraph());
    expect(store.getState().graph?.nodes).toHaveLength(2);
    expect(store.getState().isDirty).toBe(false);
    expect(store.getState().history).toEqual({ canUndo: false, canRedo: false });
    expect(store.getState().getGraph()?.entry_node_id).toBe("a");
  });

  it("addNode appends a node, names the first one the entry, and marks dirty", () => {
    store.getState().seedGraph({ ...seededGraph(), nodes: [], edges: [], entry_node_id: "" });
    const id = store.getState().addNode(DEFINITION, { x: 10, y: 20 });

    const graph = store.getState().graph;
    expect(graph?.nodes).toHaveLength(1);
    expect(graph?.nodes[0]?.id).toBe(id);
    expect(graph?.nodes[0]?.layout).toEqual({ x: 10, y: 20 });
    expect(graph?.entry_node_id).toBe(id);
    expect(store.getState().isDirty).toBe(true);
  });

  it("addNode into a non-empty graph keeps the existing entry", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().addNode(DEFINITION, { x: 5, y: 5 });
    expect(store.getState().graph?.entry_node_id).toBe("a");
    expect(store.getState().graph?.nodes).toHaveLength(3);
  });

  it("addNode falls back to an empty graph when none is seeded", () => {
    const id = store.getState().addNode(DEFINITION, { x: 1, y: 2 });
    expect(store.getState().graph?.nodes).toHaveLength(1);
    expect(store.getState().graph?.entry_node_id).toBe(id);
  });

  it("connectNodes adds an edge from a validated connection", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().connectNodes({
      source: "b",
      target: "a",
      sourceHandle: "out",
      targetHandle: "in",
    });
    const edges = store.getState().graph?.edges ?? [];
    expect(edges).toHaveLength(2);
    expect(edges[1]).toMatchObject({ source_node_id: "b", target_node_id: "a" });
  });

  it("connectNodes ignores a connection missing a handle", () => {
    store.getState().seedGraph(seededGraph());
    store
      .getState()
      .connectNodes({ source: "a", target: "b", sourceHandle: null, targetHandle: "in" });
    expect(store.getState().graph?.edges).toHaveLength(1);
  });

  it("connectNodes is a no-op before a graph is seeded", () => {
    store
      .getState()
      .connectNodes({ source: "a", target: "b", sourceHandle: "out", targetHandle: "in" });
    expect(store.getState().graph).toBeNull();
  });

  it("applyNodeChanges moves a node and marks dirty", () => {
    store.getState().seedGraph(seededGraph());
    store
      .getState()
      .applyNodeChanges([
        { id: "a", type: "position", position: { x: 40, y: 60 }, dragging: false },
      ]);
    expect(store.getState().graph?.nodes[0]?.layout).toEqual({ x: 40, y: 60 });
    expect(store.getState().isDirty).toBe(true);
  });

  it("applyNodeChanges ignores a change that leaves every layout unchanged", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().applyNodeChanges([{ id: "a", type: "select", selected: true }]);
    expect(store.getState().isDirty).toBe(false);
  });

  it("applyNodeChanges removes a node and prunes its edge", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().applyNodeChanges([{ id: "b", type: "remove" }]);
    expect(store.getState().graph?.nodes).toHaveLength(1);
    expect(store.getState().graph?.edges).toHaveLength(0);
  });

  it("applyNodeChanges ignores an added node it does not already hold", () => {
    store.getState().seedGraph(seededGraph());
    store
      .getState()
      .applyNodeChanges([
        { type: "add", item: { id: "ghost", position: { x: 0, y: 0 }, data: {} } },
      ]);
    const ids = store.getState().graph?.nodes.map((node) => node.id);
    expect(ids).toEqual(["a", "b"]);
  });

  it("applyNodeChanges is a no-op before a graph is seeded", () => {
    store.getState().applyNodeChanges([{ id: "a", type: "remove" }]);
    expect(store.getState().graph).toBeNull();
  });

  it("applyEdgeChanges removes an edge but ignores a selection change", () => {
    store.getState().seedGraph({
      ...seededGraph(),
      edges: [
        {
          id: "e1",
          source_node_id: "a",
          source_port: "out",
          target_node_id: "b",
          target_port: "in",
        },
        {
          id: "e2",
          source_node_id: "b",
          source_port: "out",
          target_node_id: "a",
          target_port: "in",
        },
      ],
    });
    store.getState().applyEdgeChanges([{ id: "e1", type: "select", selected: true }]);
    expect(store.getState().graph?.edges).toHaveLength(2);
    expect(store.getState().isDirty).toBe(false);

    store.getState().applyEdgeChanges([{ id: "e1", type: "remove" }]);
    expect(store.getState().graph?.edges.map((edge) => edge.id)).toEqual(["e2"]);
    expect(store.getState().isDirty).toBe(true);
  });

  it("applyEdgeChanges is a no-op before a graph is seeded", () => {
    store.getState().applyEdgeChanges([{ id: "e1", type: "remove" }]);
    expect(store.getState().graph).toBeNull();
  });

  it("deleteSelection removes selected nodes and edges and re-homes the entry", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    store.getState().deleteSelection();
    const graph = store.getState().graph;
    expect(graph?.nodes.map((node) => node.id)).toEqual(["b"]);
    expect(graph?.edges).toHaveLength(0);
    expect(graph?.entry_node_id).toBe("b");
    expect(store.getState().selection).toEqual({ nodeIds: [], edgeIds: [] });
  });

  it("deleteSelection prunes the bindings and scopes a removed node leaves dangling", () => {
    const literalBinding = (target: string, field: string): Binding => ({
      target_node_id: target,
      target_field: field,
      source: { kind: "literal", value: 1 },
    });
    const outputBinding = (target: string, field: string, from: string): Binding => ({
      target_node_id: target,
      target_field: field,
      source: { kind: "node_output", node_id: from, port: "out", field_path: [] },
    });
    const scope = (scopeNode: string, exit: string, body: string[]): ScopeBoundary => ({
      scope_node_id: scopeNode,
      body_node_ids: body,
      entry_port: "body",
      exit_node_id: exit,
      exit_port: "out",
    });

    store.getState().seedGraph({
      entry_node_id: "a",
      nodes: [nodeAt("a", 0, 0), nodeAt("b", 100, 0), nodeAt("c", 200, 0)],
      edges: [],
      bindings: [
        outputBinding("b", "f1", "a"), // source is the removed node → dropped
        outputBinding("b", "f2", "c"), // source survives → kept
        literalBinding("b", "f3"), // not a node reference → kept
        literalBinding("a", "f4"), // target is the removed node → dropped
      ],
      scopes: [
        scope("b", "c", []), // wholly outside the removed node → kept
        scope("b", "c", ["a"]), // body names the removed node → dropped
        scope("a", "b", ["b"]), // owner is the removed node → dropped
      ],
    });
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    store.getState().deleteSelection();

    const graph = store.getState().graph;
    expect(graph?.bindings.map((binding) => binding.target_field)).toEqual(["f2", "f3"]);
    expect(graph?.scopes).toHaveLength(1);
    expect(graph?.scopes[0]?.body_node_ids).toEqual([]);
    expect(graph?.entry_node_id).toBe("b");
  });

  it("deleteSelection emptying the graph clears the entry node", () => {
    store.getState().seedGraph({
      entry_node_id: "a",
      nodes: [nodeAt("a", 0, 0)],
      edges: [],
      bindings: [],
      scopes: [],
    });
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    store.getState().deleteSelection();
    expect(store.getState().graph?.nodes).toHaveLength(0);
    expect(store.getState().graph?.entry_node_id).toBe("");
  });

  it("deleteSelection removes a selected edge on its own", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().setSelection({ nodeIds: [], edgeIds: ["e1"] });
    store.getState().deleteSelection();
    expect(store.getState().graph?.edges).toHaveLength(0);
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("deleteSelection is a no-op with nothing selected, or before seeding", () => {
    store.getState().deleteSelection();
    expect(store.getState().graph).toBeNull();

    store.getState().seedGraph(seededGraph());
    store.getState().deleteSelection();
    expect(store.getState().isDirty).toBe(false);
  });

  it("updateNodeConfig replaces one node's config", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().updateNodeConfig("b", { message: "hi" });
    const target = store.getState().graph?.nodes.find((node) => node.id === "b");
    expect(target?.config).toEqual({ message: "hi" });
    expect(store.getState().graph?.nodes.find((node) => node.id === "a")?.config).toEqual({});
  });

  it("updateNodeConfig is a no-op before seeding", () => {
    store.getState().updateNodeConfig("b", { message: "hi" });
    expect(store.getState().graph).toBeNull();
  });

  it("upsertBinding inserts then replaces a binding on one field", () => {
    store.getState().seedGraph(seededGraph());
    const first: Binding = {
      target_node_id: "b",
      target_field: "message",
      source: { kind: "literal", value: 1 },
    };
    store.getState().upsertBinding(first);
    expect(store.getState().graph?.bindings).toHaveLength(1);

    const second: Binding = { ...first, source: { kind: "literal", value: 2 } };
    store.getState().upsertBinding(second);
    const bindings = store.getState().graph?.bindings ?? [];
    expect(bindings).toHaveLength(1);
    expect(bindings[0]?.source).toEqual({ kind: "literal", value: 2 });
  });

  it("removeBinding drops the binding on one field", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().upsertBinding({
      target_node_id: "b",
      target_field: "message",
      source: { kind: "literal", value: 1 },
    });
    store.getState().removeBinding("b", "message");
    expect(store.getState().graph?.bindings).toHaveLength(0);
  });

  it("upsertBinding and removeBinding are no-ops before seeding", () => {
    const binding: Binding = {
      target_node_id: "b",
      target_field: "message",
      source: { kind: "literal", value: 1 },
    };
    store.getState().upsertBinding(binding);
    store.getState().removeBinding("b", "message");
    expect(store.getState().graph).toBeNull();
  });

  it("insertSubgraph merges a clip and selects what it added", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().insertSubgraph({
      nodes: [nodeAt("c", 200, 0)],
      edges: [],
      bindings: [],
      scopes: [],
    });
    expect(store.getState().graph?.nodes).toHaveLength(3);
    expect(store.getState().graph?.entry_node_id).toBe("a");
    expect(store.getState().selection).toEqual({ nodeIds: ["c"], edgeIds: [] });
  });

  it("insertSubgraph into an empty graph adopts the clip's first node as the entry", () => {
    store.getState().seedGraph({ ...seededGraph(), nodes: [], edges: [], entry_node_id: "" });
    store.getState().insertSubgraph({
      nodes: [nodeAt("c", 0, 0), nodeAt("d", 50, 0)],
      edges: [],
      bindings: [],
      scopes: [],
    });
    expect(store.getState().graph?.entry_node_id).toBe("c");
  });

  it("insertSubgraph with an empty clip keeps the entry and is a no-op before seeding", () => {
    store.getState().insertSubgraph({ nodes: [], edges: [], bindings: [], scopes: [] });
    expect(store.getState().graph).toBeNull();

    store.getState().seedGraph(seededGraph());
    store.getState().insertSubgraph({ nodes: [], edges: [], bindings: [], scopes: [] });
    expect(store.getState().graph?.entry_node_id).toBe("a");
    expect(store.getState().selection).toEqual({ nodeIds: [], edgeIds: [] });
  });

  it("undo and redo step the graph through history and report the flags", () => {
    store.getState().seedGraph(seededGraph());
    const id = store.getState().addNode(DEFINITION, { x: 10, y: 10 });
    expect(store.getState().graph?.nodes).toHaveLength(3);

    store.getState().undo();
    expect(store.getState().graph?.nodes).toHaveLength(2);
    expect(store.getState().graph?.nodes.some((node) => node.id === id)).toBe(false);
    expect(store.getState().history.canRedo).toBe(true);

    store.getState().redo();
    expect(store.getState().graph?.nodes).toHaveLength(3);
    expect(store.getState().history.canUndo).toBe(true);
  });

  it("undo and redo do nothing at the ends of the stack", () => {
    store.getState().seedGraph(seededGraph());
    store.getState().undo();
    expect(store.getState().graph?.nodes).toHaveLength(2);
    store.getState().redo();
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("undo and redo do nothing before a graph is seeded", () => {
    store.getState().undo();
    store.getState().redo();
    expect(store.getState().graph).toBeNull();
  });

  it("getSelectedNode returns the node only when exactly one is selected", () => {
    store.getState().seedGraph(seededGraph());
    expect(store.getState().getSelectedNode()).toBeNull();

    store.getState().setSelection({ nodeIds: ["a", "b"], edgeIds: [] });
    expect(store.getState().getSelectedNode()).toBeNull();

    store.getState().setSelection({ nodeIds: ["b"], edgeIds: [] });
    expect(store.getState().getSelectedNode()?.id).toBe("b");

    store.getState().setSelection({ nodeIds: ["missing"], edgeIds: [] });
    expect(store.getState().getSelectedNode()).toBeNull();
  });

  it("getSelectedNode is null before a graph is seeded", () => {
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    expect(store.getState().getSelectedNode()).toBeNull();
  });
});
