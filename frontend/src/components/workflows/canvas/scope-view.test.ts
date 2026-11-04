import { describe, expect, it } from "vitest";

import type { NodeInstance, ScopeBoundary, WorkflowGraph } from "@/lib/workflows/types";

import { currentScopeId, owningScopeByNode, scopedGraph, visibleNodeIds } from "./scope-view";

function node(id: string): NodeInstance {
  return { id, definition_id: "act", definition_version: 1, config: {}, layout: { x: 0, y: 0 } };
}

function edge(id: string, source: string, target: string): WorkflowGraph["edges"][number] {
  return {
    id,
    source_node_id: source,
    source_port: "out",
    target_node_id: target,
    target_port: "in",
  };
}

function scope(scopeNodeId: string, body: string[]): ScopeBoundary {
  return {
    scope_node_id: scopeNodeId,
    body_node_ids: body,
    entry_port: "body",
    exit_node_id: scopeNodeId,
    exit_port: "out",
  };
}

/**
 * A two-level nesting: the root holds `root1` and the outer loop `F1`; `F1`'s body
 * holds `b1` and the inner loop `F2`; `F2`'s body holds `c1` and `c2`. `body_node_ids`
 * is transitive, so `F1`'s body also lists `c1`/`c2`.
 */
function nestedGraph(): WorkflowGraph {
  return {
    entry_node_id: "root1",
    nodes: [node("root1"), node("F1"), node("b1"), node("F2"), node("c1"), node("c2")],
    edges: [
      edge("e_root", "root1", "F1"), // both at root
      edge("e_body", "F1", "b1"), // crosses root -> F1's body
      edge("e_inner", "b1", "F2"), // both in F1's body
      edge("e_deep", "F2", "c1"), // crosses F1's body -> F2's body
      edge("e_c", "c1", "c2"), // both in F2's body
    ],
    bindings: [{ target_node_id: "c1", target_field: "x", source: { kind: "literal", value: 1 } }],
    scopes: [scope("F1", ["b1", "F2", "c1", "c2"]), scope("F2", ["c1", "c2"])],
  };
}

describe("scope-view", () => {
  it("names the current scope as the last path entry, or null at the root", () => {
    expect(currentScopeId([])).toBeNull();
    expect(currentScopeId(["F1"])).toBe("F1");
    expect(currentScopeId(["F1", "F2"])).toBe("F2");
  });

  it("maps each node to its innermost owning scope, root nodes to null", () => {
    const owners = owningScopeByNode(nestedGraph());
    expect(owners.get("root1")).toBeNull();
    // A scope owner is not a member of its own body, so it belongs to the outer scope.
    expect(owners.get("F1")).toBeNull();
    expect(owners.get("b1")).toBe("F1");
    expect(owners.get("F2")).toBe("F1");
    // In both bodies; the innermost (smallest) wins.
    expect(owners.get("c1")).toBe("F2");
    expect(owners.get("c2")).toBe("F2");
  });

  it("shows a scope's direct members only — not a deeper scope's body", () => {
    const graph = nestedGraph();
    expect([...visibleNodeIds(graph, [])]).toEqual(["root1", "F1"]);
    expect([...visibleNodeIds(graph, ["F1"])]).toEqual(["b1", "F2"]);
    expect([...visibleNodeIds(graph, ["F1", "F2"])]).toEqual(["c1", "c2"]);
  });

  it("keeps an edge only when both its endpoints are visible in the scope", () => {
    const graph = nestedGraph();

    const root = scopedGraph(graph, []);
    expect(root.nodes.map((n) => n.id)).toEqual(["root1", "F1"]);
    expect(root.edges.map((e) => e.id)).toEqual(["e_root"]);

    const outer = scopedGraph(graph, ["F1"]);
    expect(outer.nodes.map((n) => n.id)).toEqual(["b1", "F2"]);
    expect(outer.edges.map((e) => e.id)).toEqual(["e_inner"]);

    const inner = scopedGraph(graph, ["F1", "F2"]);
    expect(inner.nodes.map((n) => n.id)).toEqual(["c1", "c2"]);
    expect(inner.edges.map((e) => e.id)).toEqual(["e_c"]);
  });

  it("carries bindings, scopes and the entry id through unchanged", () => {
    const graph = nestedGraph();
    const scoped = scopedGraph(graph, ["F1"]);
    expect(scoped.entry_node_id).toBe("root1");
    expect(scoped.bindings).toBe(graph.bindings);
    expect(scoped.scopes).toBe(graph.scopes);
  });

  it("shows the whole flat graph when there are no scopes", () => {
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [node("a"), node("b")],
      edges: [edge("e", "a", "b")],
      bindings: [],
      scopes: [],
    };
    const scoped = scopedGraph(graph, []);
    expect(scoped.nodes).toHaveLength(2);
    expect(scoped.edges).toHaveLength(1);
  });
});
