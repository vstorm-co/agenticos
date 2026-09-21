import { describe, expect, it } from "vitest";

import { sampleGraph } from "./fixtures";
import { collectIds, graphsEqual, replaceScope, scopeAt } from "./typed-graph";

describe("typed graph helpers", () => {
  it("lists every id at every depth", () => {
    expect(collectIds(sampleGraph()).sort()).toEqual(
      ["start", "each-file", "extract", "each-line", "write-line", "end"].sort(),
    );
  });

  it("walks a path of foreach ids to the scope it names", () => {
    const scope = scopeAt(sampleGraph(), ["each-file", "each-line"]);
    expect(scope.nodes.map((node) => node.id)).toEqual(["write-line"]);
  });

  it("refuses a path through a node that is not a foreach", () => {
    expect(() => scopeAt(sampleGraph(), ["start"])).toThrow(/not a foreach/);
    expect(() => scopeAt(sampleGraph(), ["missing"])).toThrow(/not a foreach/);
    expect(() => replaceScope(sampleGraph(), ["start"], { nodes: [], edges: [] })).toThrow(
      /not a foreach/,
    );
  });

  it("replaces one scope and shares the rest", () => {
    const graph = sampleGraph();
    const next = replaceScope(graph, ["each-file"], { nodes: [], edges: [] });
    expect(scopeAt(next, ["each-file"]).nodes).toEqual([]);
    expect(next.nodes[0]).toBe(graph.nodes[0]);
    expect(replaceScope(graph, [], next)).toBe(next);
  });

  it("compares graphs by content, ignoring key order and undefined", () => {
    const a = sampleGraph();
    const b = structuredClone(a);
    expect(graphsEqual(a, b)).toBe(true);
    const first = b.nodes[0];
    if (!first) throw new Error("fixture has no nodes");
    first.label = "changed";
    expect(graphsEqual(a, b)).toBe(false);
    expect(graphsEqual({ nodes: [], edges: [] }, { edges: [], nodes: [] })).toBe(true);
  });
});
