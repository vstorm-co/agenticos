import { describe, expect, it } from "vitest";

import { DEBUG_ECHO, echo, edge, makeCatalog, makeDefinition, node, port, graph } from "./fixtures";
import {
  definitionFor,
  deriveScopes,
  forwardEdges,
  indexCatalog,
  kahn,
  loopItemOf,
  nodeIds,
  nodeScopeMap,
  resolveDefinitions,
} from "./topology";

const FOREACH = (id: string) =>
  makeDefinition({
    id,
    kind: "control",
    ports: [port("in", "input", null), port("done", "output", null)],
  });

const NO_EXIT_CONTROL = makeDefinition({
  id: "control.no_exit",
  kind: "control",
  ports: [port("in", "input", null)],
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
  it("ignores a non-control node and a control node with no way out", () => {
    const catalog = makeCatalog([DEBUG_ECHO, NO_EXIT_CONTROL]);
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("c", "control.no_exit")],
      edges: [edge("e1", "a", "out", "c", "in")],
    });
    expect(deriveScopes(g, resolveDefinitions(g, catalog))).toEqual([]);
  });

  it("derives a body from the steps naming the loop, never what is wired after it", () => {
    const catalog = makeCatalog([DEBUG_ECHO, FOREACH("control.foreach")]);
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("loop", "control.foreach"),
        { ...echo("body"), scope_id: "loop" },
        echo("after"),
      ],
      edges: [edge("e1", "entry", "out", "loop", "in"), edge("e3", "loop", "done", "after", "in")],
    });
    const [scope] = deriveScopes(g, resolveDefinitions(g, catalog));
    expect(scope?.body_node_ids).toEqual(["body"]);
    expect(scope).toMatchObject({ exit_node_id: "loop", exit_port: "done" });
  });

  it("holds a nested body in its outer one, and a loop named inside itself stays finite", () => {
    const catalog = makeCatalog([DEBUG_ECHO, FOREACH("control.foreach")]);
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("outer", "control.foreach"),
        { ...node("inner", "control.foreach"), scope_id: "outer" },
        { ...echo("leaf"), scope_id: "inner" },
        { ...node("a", "control.foreach"), scope_id: "b" },
        { ...node("b", "control.foreach"), scope_id: "a" },
      ],
    });
    const scopes = deriveScopes(g, resolveDefinitions(g, catalog));
    const outer = scopes.find((scope) => scope.scope_node_id === "outer");
    expect(new Set(outer?.body_node_ids)).toEqual(new Set(["inner", "leaf"]));
    expect(scopes.find((scope) => scope.scope_node_id === "a")?.body_node_ids).toEqual(["b"]);
  });

  it("finds a loop's item step by membership", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), { ...node("i", "loop.item"), scope_id: "loop" }],
    });
    expect(loopItemOf(g, "loop")).toBe("i");
    expect(loopItemOf(g, "other")).toBeNull();
  });
});

describe("nodeScopeMap", () => {
  it("resolves ownership to the innermost scope regardless of order", () => {
    const scopes = [
      {
        scope_node_id: "outer",
        body_node_ids: ["inner", "leaf"],
        exit_node_id: "outer",
        exit_port: "done",
      },
      {
        scope_node_id: "inner",
        body_node_ids: ["leaf"],
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
