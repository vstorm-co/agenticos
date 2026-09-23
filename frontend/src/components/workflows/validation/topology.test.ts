import { describe, expect, it } from "vitest";

import { DEBUG_ECHO, echo, edge, makeCatalog, makeDefinition, node, port, graph } from "./fixtures";
import {
  allDominators,
  definitionFor,
  deriveScopes,
  dominators,
  forwardEdges,
  indexCatalog,
  kahn,
  nodeIds,
  nodeScopeMap,
  resolveDefinitions,
} from "./topology";

const FOREACH = (id: string) =>
  makeDefinition({
    id,
    kind: "control",
    ports: [port("in", "input", null), port("body", "output", null), port("done", "output", null)],
  });

const SINGLE_PORT_CONTROL = makeDefinition({
  id: "control.single_port",
  kind: "control",
  ports: [port("in", "input", null), port("out", "output", null)],
});

describe("indexCatalog / resolveDefinitions / definitionFor", () => {
  it("resolves a node's definition and reports null for an unknown version", () => {
    const catalog = makeCatalog([DEBUG_ECHO]);
    expect(indexCatalog(catalog).size).toBe(1);
    const g = graph({ entry: "a", nodes: [echo("a"), node("b", "debug.echo", {}, 99)] });
    const map = resolveDefinitions(g, catalog);
    expect(map.get("a")).toBe(DEBUG_ECHO);
    expect(map.get("b")).toBeNull();
  });

  it("definitionFor returns the definition, a stored null, or null for an absent node", () => {
    const catalog = makeCatalog([DEBUG_ECHO]);
    const g = graph({ entry: "a", nodes: [echo("a"), node("b", "debug.echo", {}, 99)] });
    const map = resolveDefinitions(g, catalog);
    expect(definitionFor(map, "a")).toBe(DEBUG_ECHO);
    expect(definitionFor(map, "b")).toBeNull();
    expect(definitionFor(map, "not-in-map")).toBeNull();
  });
});

describe("nodeIds / forwardEdges", () => {
  it("collects node ids and groups outgoing edges by source", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), echo("b"), echo("c")],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "a", "out", "c", "in")],
    });
    expect(nodeIds(g)).toEqual(new Set(["a", "b", "c"]));
    expect(forwardEdges(g).get("a")).toHaveLength(2);
  });
});

describe("deriveScopes", () => {
  it("ignores a non-control node and a control node with fewer than two output ports", () => {
    const catalog = makeCatalog([DEBUG_ECHO, SINGLE_PORT_CONTROL]);
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("c", "control.single_port")],
      edges: [edge("e1", "a", "out", "c", "in")],
    });
    expect(deriveScopes(g, resolveDefinitions(g, catalog))).toEqual([]);
  });

  it("derives a body from the entry port without absorbing what is downstream of the loop", () => {
    const catalog = makeCatalog([DEBUG_ECHO, FOREACH("control.foreach")]);
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("loop", "control.foreach"), echo("body"), echo("after")],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "body", "in"),
        edge("e3", "loop", "done", "after", "in"),
      ],
    });
    const [scope] = deriveScopes(g, resolveDefinitions(g, catalog));
    expect(scope?.body_node_ids).toEqual(["body"]);
    expect(scope?.exit_node_id).toBe("loop");
  });

  it("visits each body node once through a diamond and a loop-back edge", () => {
    const catalog = makeCatalog([DEBUG_ECHO, FOREACH("control.foreach")]);
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("loop", "control.foreach"), echo("b1"), echo("b2"), echo("b3")],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "b1", "in"),
        edge("e3", "loop", "body", "b2", "in"),
        edge("e4", "b1", "out", "b3", "in"),
        edge("e5", "b2", "out", "b3", "in"),
        edge("e6", "b3", "out", "loop", "in"),
        edge("e7", "b3", "out", "b1", "in"),
      ],
    });
    const [scope] = deriveScopes(g, resolveDefinitions(g, catalog));
    expect(new Set(scope?.body_node_ids)).toEqual(new Set(["b1", "b2", "b3"]));
  });
});

describe("nodeScopeMap", () => {
  it("resolves ownership to the innermost scope regardless of order", () => {
    const scopes = [
      {
        scope_node_id: "outer",
        body_node_ids: ["inner", "leaf"],
        entry_port: "body",
        exit_node_id: "outer",
        exit_port: "done",
      },
      {
        scope_node_id: "inner",
        body_node_ids: ["leaf"],
        entry_port: "body",
        exit_node_id: "inner",
        exit_port: "done",
      },
    ];
    expect(nodeScopeMap(scopes).get("leaf")).toBe("inner");
    expect(nodeScopeMap([...scopes].reverse()).get("leaf")).toBe("inner");
    expect(nodeScopeMap(scopes).get("inner")).toBe("outer");
  });
});

describe("kahn", () => {
  it("orders a chain, ignores an edge whose endpoint is outside the set", () => {
    const { order, cyclic, predecessors } = kahn(
      ["a", "b"],
      [edge("e1", "a", "out", "b", "in"), edge("e2", "a", "out", "stray", "in")],
    );
    expect(order).toEqual(["a", "b"]);
    expect(cyclic.size).toBe(0);
    expect(predecessors.get("b")).toEqual(new Set(["a"]));
  });

  it("reports every node of a cycle as unordered", () => {
    const { cyclic } = kahn(
      ["a", "b"],
      [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "a", "in")],
    );
    expect(cyclic).toEqual(new Set(["a", "b"]));
  });
});

describe("dominators", () => {
  it("intersects predecessor dominators and skips a node with no resolved predecessors", () => {
    // `island` is absent from the predecessors map entirely; `orphan` is present
    // with an empty set. Both have no resolved predecessor, so neither enters the
    // dominator map — and a single-predecessor node's set is never mutated by a
    // later node's intersection.
    const predecessors = new Map([
      ["root", new Set<string>()],
      ["mid", new Set(["root"])],
      ["join", new Set(["root", "mid"])],
      ["orphan", new Set<string>()],
    ]);
    const dom = dominators(["root", "mid", "join", "orphan", "island"], predecessors, "root");
    expect(dom.get("join")).toEqual(new Set(["root", "join"]));
    expect(dom.get("mid")).toEqual(new Set(["root", "mid"]));
    expect(dom.has("orphan")).toBe(false);
    expect(dom.has("island")).toBe(false);
  });
});

describe("allDominators", () => {
  it("is empty when the outer order is a cycle", () => {
    const g = graph({ entry: "a", nodes: [echo("a")] });
    expect(allDominators(g, [], new Map(), null).size).toBe(0);
  });

  it("is empty when the entry is not a real node", () => {
    const g = graph({ entry: "ghost", nodes: [echo("a")] });
    expect(allDominators(g, [], new Map(), ["a"]).size).toBe(0);
  });

  it("skips a scope body that has a cycle of its own", () => {
    const catalog = makeCatalog([DEBUG_ECHO, FOREACH("control.foreach")]);
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("loop", "control.foreach"), echo("x"), echo("y")],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "x", "in"),
        edge("e3", "x", "out", "y", "in"),
        edge("e4", "y", "out", "x", "in"),
      ],
    });
    const definitions = resolveDefinitions(g, catalog);
    const scopes = deriveScopes(g, definitions);
    const outer = kahn(["entry", "loop"], [edge("e1", "entry", "out", "loop", "in")]);
    const dom = allDominators(g, scopes, outer.predecessors, outer.order);
    // The body members get no dominator verdict, but the outer nodes still do.
    expect(dom.get("entry")).toEqual(new Set(["entry"]));
    expect(dom.has("x")).toBe(false);
  });
});
