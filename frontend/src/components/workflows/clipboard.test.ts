import { describe, expect, it } from "vitest";

import type {
  Binding,
  NodeInstance,
  NodeOutputRef,
  ScopeBoundary,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";
import type { EditorSelection, WorkflowClipboard } from "@/stores/workflow-editor-store";

import { copySelection, pasteClipboard } from "./clipboard";

function node(id: string, config: Record<string, unknown> = {}): NodeInstance {
  return { id, definition_id: "kind", definition_version: 1, config, layout: { x: 10, y: 20 } };
}

function edge(id: string, source: string, target: string): WorkflowEdge {
  return {
    id,
    source_node_id: source,
    source_port: "out",
    target_node_id: target,
    target_port: "in",
  };
}

function nodeOutputRef(nodeId: string): NodeOutputRef {
  return { kind: "node_output", node_id: nodeId, port: "out", field_path: [] };
}

function binding(target: string, source: Binding["source"]): Binding {
  return { target_node_id: target, target_field: "field", source };
}

function scope(scopeId: string, exitId: string, body: string[]): ScopeBoundary {
  return {
    scope_node_id: scopeId,
    body_node_ids: body,
    entry_port: "body",
    exit_node_id: exitId,
    exit_port: "next",
  };
}

function select(nodeIds: string[], edgeIds: string[] = []): EditorSelection {
  return { nodeIds, edgeIds };
}

/** A sequential id minter, so remapped ids are predictable in assertions. */
function minter(): () => string {
  let n = 0;
  return () => `new-${(n += 1)}`;
}

describe("copySelection", () => {
  it("returns null when no node is selected", () => {
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [node("a")],
      edges: [],
      bindings: [],
      scopes: [],
    };
    expect(copySelection(graph, select([]))).toBeNull();
    // An edge-only selection copies nothing either — a paste needs its nodes.
    expect(copySelection(graph, select([], ["e1"]))).toBeNull();
  });

  it("copies the induced subgraph and leaves external references out", () => {
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [node("a"), node("b"), node("outside")],
      edges: [edge("e-internal", "a", "b"), edge("e-external", "b", "outside")],
      bindings: [
        binding("a", nodeOutputRef("b")), // target copied → copied
        binding("outside", nodeOutputRef("a")), // target not copied → dropped
      ],
      scopes: [],
    };

    const clip = copySelection(graph, select(["a", "b"]));
    expect(clip).not.toBeNull();
    expect(clip?.nodes.map((entry) => entry.id)).toEqual(["a", "b"]);
    expect(clip?.edges.map((entry) => entry.id)).toEqual(["e-internal"]);
    expect(clip?.bindings).toHaveLength(1);
    expect(clip?.bindings[0]?.target_node_id).toBe("a");
  });

  it("keeps a scope only when every node it names is contained", () => {
    const nodes = [node("s"), node("body"), node("exit"), node("stray")];
    const base = {
      entry_node_id: "s",
      nodes,
      edges: [] as WorkflowEdge[],
      bindings: [] as Binding[],
    };

    const contained = copySelection(
      { ...base, scopes: [scope("s", "exit", ["body"])] },
      select(["s", "body", "exit"]),
    );
    expect(contained?.scopes).toHaveLength(1);

    // Body member outside the selection.
    expect(
      copySelection(
        { ...base, scopes: [scope("s", "exit", ["body", "stray"])] },
        select(["s", "body", "exit"]),
      )?.scopes,
    ).toHaveLength(0);

    // Owner node outside the selection.
    expect(
      copySelection({ ...base, scopes: [scope("s", "exit", ["body"])] }, select(["body", "exit"]))
        ?.scopes,
    ).toHaveLength(0);

    // Exit node outside the selection.
    expect(
      copySelection({ ...base, scopes: [scope("s", "exit", ["body"])] }, select(["s", "body"]))
        ?.scopes,
    ).toHaveLength(0);
  });

  it("snapshots the graph, so later edits to the clip do not reach it", () => {
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [node("a")],
      edges: [],
      bindings: [],
      scopes: [],
    };
    const clip = copySelection(graph, select(["a"]));
    clip!.nodes[0]!.config.mutated = true;
    expect(graph.nodes[0]?.config).toEqual({});
  });
});

describe("pasteClipboard", () => {
  it("re-ids every node and edge and remaps the internal edge endpoints", () => {
    const clip: WorkflowClipboard = {
      nodes: [node("a"), node("b")],
      edges: [edge("e", "a", "b")],
      bindings: [],
      scopes: [],
    };
    const result = pasteClipboard(clip, minter());

    expect(result.idMap).toEqual({ a: "new-1", b: "new-2" });
    expect(result.clipboard.nodes.map((entry) => entry.id)).toEqual(["new-1", "new-2"]);
    const pastedEdge = result.clipboard.edges[0]!;
    expect(pastedEdge.id).toBe("new-3"); // a fresh edge id, not the old "e"
    expect(pastedEdge.source_node_id).toBe("new-1");
    expect(pastedEdge.target_node_id).toBe("new-2");
  });

  it("remaps a binding target, an internal source, but not an external or non-node source", () => {
    const externalRef = nodeOutputRef("elsewhere");
    const literal: Binding["source"] = { kind: "literal", value: 42 };
    const clip: WorkflowClipboard = {
      nodes: [node("a"), node("b")],
      edges: [],
      bindings: [
        binding("a", nodeOutputRef("b")), // internal: node_id remaps
        binding("b", externalRef), // external: node_id untouched
        binding("a", literal), // non-node source: untouched
      ],
      scopes: [],
    };
    const result = pasteClipboard(clip, minter());

    const [internal, external, constant] = result.clipboard.bindings;
    expect(internal?.target_node_id).toBe("new-1");
    expect((internal?.source as NodeOutputRef).node_id).toBe("new-2");
    expect(external?.target_node_id).toBe("new-2");
    expect((external?.source as NodeOutputRef).node_id).toBe("elsewhere");
    expect(constant?.source).toEqual(literal);
  });

  it("remaps every id a scope boundary names", () => {
    const clip: WorkflowClipboard = {
      nodes: [node("s"), node("body"), node("exit")],
      edges: [],
      bindings: [],
      scopes: [scope("s", "exit", ["body"])],
    };
    const result = pasteClipboard(clip, minter());
    const pasted = result.clipboard.scopes[0]!;
    expect(pasted.scope_node_id).toBe(result.idMap.s);
    expect(pasted.exit_node_id).toBe(result.idMap.exit);
    expect(pasted.body_node_ids).toEqual([result.idMap.body]);
  });

  it("offsets pasted node layouts, defaulting to no shift", () => {
    const clip: WorkflowClipboard = {
      nodes: [node("a")],
      edges: [],
      bindings: [],
      scopes: [],
    };
    expect(pasteClipboard(clip, minter()).clipboard.nodes[0]?.layout).toEqual({ x: 10, y: 20 });
    expect(pasteClipboard(clip, minter(), { x: 40, y: -5 }).clipboard.nodes[0]?.layout).toEqual({
      x: 50,
      y: 15,
    });
  });

  it("never inspects config, so a new node kind needs no clipboard change", () => {
    // `config` holds a string equal to a copied node id; a config-reading remap
    // would corrupt it. The remap keys only on the binding list, so it is kept.
    const config = { note: "b", nested: { ref: "a" } };
    const clip: WorkflowClipboard = {
      nodes: [node("a", config), node("b")],
      edges: [],
      bindings: [],
      scopes: [],
    };
    const pasted = pasteClipboard(clip, minter()).clipboard.nodes[0]!;
    expect(pasted.config).toEqual({ note: "b", nested: { ref: "a" } });
  });

  it("leaves an edge endpoint that names no copied node unchanged", () => {
    // A hand-built clip whose edge reaches a node not in the copied set exercises
    // the identity fallback; copySelection never produces one, but paste must not
    // invent an id for it.
    const clip: WorkflowClipboard = {
      nodes: [node("a")],
      edges: [edge("e", "a", "orphan")],
      bindings: [],
      scopes: [],
    };
    const pastedEdge = pasteClipboard(clip, minter()).clipboard.edges[0]!;
    expect(pastedEdge.source_node_id).toBe("new-1");
    expect(pastedEdge.target_node_id).toBe("orphan");
  });

  it("does not mutate the stored clip", () => {
    const clip: WorkflowClipboard = {
      nodes: [node("a")],
      edges: [],
      bindings: [],
      scopes: [],
    };
    pasteClipboard(clip, minter(), { x: 100, y: 100 });
    expect(clip.nodes[0]?.id).toBe("a");
    expect(clip.nodes[0]?.layout).toEqual({ x: 10, y: 20 });
  });
});
