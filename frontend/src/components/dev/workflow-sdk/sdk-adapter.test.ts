import { describe, expect, it } from "vitest";

import { sampleGraph } from "./fixtures";
import { syntheticGraph } from "./perf";
import { GraphParseError, fromSdkScope, toSdkScope } from "./sdk-adapter";
import { graphsEqual, scopeAt, type WorkflowGraph } from "./typed-graph";

/** Every scope of a graph: the root, then each foreach body, recursively. */
function scopes(graph: WorkflowGraph, path: string[] = []): string[][] {
  return [
    path,
    ...graph.nodes.flatMap((node) =>
      node.config.kind === "foreach" ? scopes(node.config.body, [...path, node.id]) : [],
    ),
  ];
}

describe("typed graph <-> SDK document", () => {
  it("round-trips every scope of the sample graph unchanged", () => {
    const graph = sampleGraph();
    for (const path of scopes(graph)) {
      const scope = scopeAt(graph, path);
      const sdk = toSdkScope(scope);
      expect(graphsEqual(scope, fromSdkScope(scope, sdk.nodes, sdk.edges))).toBe(true);
    }
  });

  it("round-trips a synthetic graph", () => {
    const graph = syntheticGraph(40);
    const sdk = toSdkScope(graph);
    expect(graphsEqual(graph, fromSdkScope(graph, sdk.nodes, sdk.edges))).toBe(true);
  });

  it("keeps what the SDK never held: foreach bodies and the on_conflict dict", () => {
    const graph = sampleGraph();
    const sdk = toSdkScope(graph);
    // The SDK's node data carries no body at all.
    expect(JSON.stringify(sdk.nodes)).not.toContain("write-line");
    const back = fromSdkScope(graph, sdk.nodes, sdk.edges);
    expect(scopeAt(back, ["each-file", "each-line"]).nodes[0]?.id).toBe("write-line");

    const body = scopeAt(graph, ["each-file", "each-line"]);
    const inner = toSdkScope(body);
    const innerBack = fromSdkScope(body, inner.nodes, inner.edges);
    expect(innerBack.nodes[0]?.config).toMatchObject({ on_conflict: { amount: "keep_new" } });
  });

  it("gives a foreach node the SDK has no body for an empty one", () => {
    const graph = sampleGraph();
    const sdk = toSdkScope(graph);
    const back = fromSdkScope({ nodes: [], edges: [] }, sdk.nodes, sdk.edges);
    expect(scopeAt(back, ["each-file"]).nodes).toEqual([]);
  });

  it("drops the validation results the SDK writes into properties", () => {
    const graph = sampleGraph();
    const sdk = toSdkScope(graph);
    const [first] = sdk.nodes;
    if (!first) throw new Error("no node");
    first.data.properties = {
      ...first.data.properties,
      errors: [{ keyword: "x" }],
      customErrors: [],
    } as never;
    const back = fromSdkScope(graph, sdk.nodes, sdk.edges);
    expect(JSON.stringify(back)).not.toContain("errors");
  });

  it("maps a missing key column to null and back", () => {
    const graph = scopeAt(sampleGraph(), ["each-file", "each-line"]);
    const sdk = toSdkScope(graph);
    const [node] = sdk.nodes;
    if (!node) throw new Error("no node");
    node.data.properties = { ...node.data.properties, key_column: "" };
    const back = fromSdkScope(graph, sdk.nodes, sdk.edges);
    expect(back.nodes[0]?.config).toMatchObject({ key_column: null });
    expect(toSdkScope(back).nodes[0]?.data.properties.key_column).toBe("");
  });

  it("names every problem instead of coercing", () => {
    const graph = scopeAt(sampleGraph(), ["each-file", "each-line"]);
    const sdk = toSdkScope(graph);
    const [node] = sdk.nodes;
    if (!node) throw new Error("no node");
    node.data.properties = {
      ...node.data.properties,
      mode: "merge",
      batch_size: 1.5,
      table_id: 3,
      mappings: [{ column: "", value: "x" }, { column: 1 }, "nope"],
    };
    expect.assertions(6);
    try {
      fromSdkScope(graph, sdk.nodes, sdk.edges);
    } catch (error) {
      expect(error).toBeInstanceOf(GraphParseError);
      const { problems } = error as GraphParseError;
      expect(problems.some((p) => p.includes("mode"))).toBe(true);
      expect(problems.some((p) => p.includes("batch_size"))).toBe(true);
      expect(problems.some((p) => p.includes("table_id"))).toBe(true);
      expect(problems.some((p) => p.includes("has no column"))).toBe(true);
      expect(problems.filter((p) => p.includes("mappings")).length).toBe(3);
    }
  });

  it("rejects a non-list of mappings, an unknown type, a duplicate id and a stray edge", () => {
    const graph = sampleGraph();
    const sdk = toSdkScope(graph);
    const [a, b] = sdk.nodes;
    if (!a || !b) throw new Error("no nodes");
    const table = scopeAt(graph, ["each-file", "each-line"]);
    const tableSdk = toSdkScope(table);
    const [t] = tableSdk.nodes;
    if (!t) throw new Error("no node");
    t.data.properties = { ...t.data.properties, mappings: "x" };
    expect(() => fromSdkScope(table, tableSdk.nodes, tableSdk.edges)).toThrow(/not a list/);

    const odd = { ...b, id: a.id, data: { ...b.data, type: "mystery" } };
    const stray = { ...sdk.edges[0]!, id: "e-x", target: "nowhere" };
    expect.assertions(4);
    try {
      fromSdkScope(graph, [a, odd], [stray]);
    } catch (error) {
      const { problems } = error as GraphParseError;
      expect(problems.some((p) => p.includes("appears twice"))).toBe(true);
      expect(problems.some((p) => p.includes("mystery"))).toBe(true);
      expect(problems.some((p) => p.includes("not in this scope"))).toBe(true);
    }
  });

  it("rejects a foreach with a bad concurrency", () => {
    const graph = sampleGraph();
    const sdk = toSdkScope(graph);
    const foreach = sdk.nodes.find((node) => node.data.type === "foreach");
    if (!foreach) throw new Error("no foreach");
    foreach.data.properties = { ...foreach.data.properties, concurrency: 0 };
    expect(() => fromSdkScope(graph, sdk.nodes, sdk.edges)).toThrow(/concurrency/);
  });
});
