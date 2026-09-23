import { describe, expect, it } from "vitest";

import type {
  JsonSchema,
  NodeDefinition,
  NodeInstance,
  WorkflowGraph,
} from "@/lib/workflows/types";

import {
  buildCatalogMap,
  definitionsByNode,
  edgeVariant,
  ERROR_PORT_ID,
  isConnectionValid,
  isErrorPort,
  selectionFromFlow,
  toFlowEdges,
  toFlowNodes,
} from "./graph-adapter";

function def(overrides: Partial<NodeDefinition> = {}): NodeDefinition {
  return {
    id: "act",
    version: 1,
    name: "Act",
    category: "c",
    description: "",
    kind: "action",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: [],
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
    ...overrides,
  };
}

function instance(id: string, definitionId: string, version: number): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: version,
    config: {},
    layout: { x: 1, y: 2 },
  };
}

const OBJECT_A: JsonSchema = { type: "object", title: "A", properties: { a: { type: "string" } } };
const OBJECT_B: JsonSchema = { type: "object", title: "B", properties: { b: { type: "string" } } };

const ACTION = def({
  id: "act",
  ports: [
    { id: "in", label: "In", kind: "input", schema: OBJECT_A },
    { id: "out", label: "Out", kind: "output", schema: OBJECT_A },
  ],
});
const CONTROL = def({
  id: "ctrl",
  kind: "control",
  ports: [
    { id: "in", label: "In", kind: "input", schema: null },
    { id: "then", label: "Then", kind: "output", schema: null },
    { id: ERROR_PORT_ID, label: "Error", kind: "output", schema: null },
  ],
});

function graphOf(nodes: NodeInstance[], edges: WorkflowGraph["edges"] = []): WorkflowGraph {
  return { entry_node_id: nodes[0]?.id ?? "", nodes, edges, bindings: [], scopes: [] };
}

describe("graph-adapter", () => {
  it("resolves each node's definition by id and pinned version", () => {
    const catalog = buildCatalogMap([ACTION, CONTROL]);
    const graph = graphOf([instance("a", "act", 1), instance("g", "act", 9)]);
    const byNode = definitionsByNode(graph, catalog);
    expect(byNode.get("a")).toBe(ACTION);
    expect(byNode.get("g")).toBeNull();
  });

  it("names only the error output port", () => {
    expect(isErrorPort({ id: ERROR_PORT_ID, kind: "output" })).toBe(true);
    expect(isErrorPort({ id: "out", kind: "output" })).toBe(false);
    expect(isErrorPort({ id: ERROR_PORT_ID, kind: "input" })).toBe(false);
  });

  it("projects nodes with their kind as the flow type, falling back to action", () => {
    const catalog = buildCatalogMap([ACTION, CONTROL]);
    const graph = graphOf([
      instance("a", "act", 1),
      instance("c", "ctrl", 1),
      instance("g", "act", 9),
    ]);
    const byNode = definitionsByNode(graph, catalog);
    const flow = toFlowNodes(graph, byNode, false);
    expect(flow.map((node) => node.type)).toEqual(["action", "control", "action"]);
    expect(flow[0]?.position).toEqual({ x: 1, y: 2 });
    expect(flow[0]?.data.readOnly).toBe(false);
    expect(flow[2]?.data.definition).toBeNull();
  });

  it("classifies an edge as error, branch or data", () => {
    expect(edgeVariant(ERROR_PORT_ID, ACTION)).toEqual({ variant: "error", label: null });
    expect(edgeVariant("then", CONTROL)).toEqual({ variant: "branch", label: "Then" });
    // A control output the definition does not list still labels with the port id.
    expect(edgeVariant("missing", CONTROL)).toEqual({ variant: "branch", label: "missing" });
    expect(edgeVariant("out", ACTION)).toEqual({ variant: "data", label: null });
    expect(edgeVariant("out", null)).toEqual({ variant: "data", label: null });
  });

  it("projects edges with the source node's variant, even an unknown source", () => {
    const catalog = buildCatalogMap([ACTION, CONTROL]);
    const graph = graphOf(
      [instance("a", "act", 1), instance("c", "ctrl", 1), instance("g", "act", 9)],
      [
        {
          id: "e1",
          source_node_id: "a",
          source_port: "out",
          target_node_id: "c",
          target_port: "in",
        },
        {
          id: "e2",
          source_node_id: "c",
          source_port: "then",
          target_node_id: "a",
          target_port: "in",
        },
        {
          id: "e3",
          source_node_id: "g",
          source_port: "out",
          target_node_id: "a",
          target_port: "in",
        },
      ],
    );
    const byNode = definitionsByNode(graph, catalog);
    const flow = toFlowEdges(graph, byNode);
    expect(flow[0]).toMatchObject({ id: "e1", type: "workflow", data: { variant: "data" } });
    expect(flow[1]?.data).toEqual({ variant: "branch", label: "Then" });
    // An edge from an unknown-definition node is a plain data edge.
    expect(flow[2]?.data).toEqual({ variant: "data", label: null });
  });

  it("maps an @xyflow selection to the store's node and edge id lists", () => {
    expect(selectionFromFlow([{ id: "a" }, { id: "b" }], [{ id: "e1" }])).toEqual({
      nodeIds: ["a", "b"],
      edgeIds: ["e1"],
    });
    expect(selectionFromFlow([], [])).toEqual({ nodeIds: [], edgeIds: [] });
  });

  it("accepts a compatible connection and refuses everything else", () => {
    const catalog = buildCatalogMap([ACTION, CONTROL]);
    const graph = graphOf([
      instance("a", "act", 1),
      instance("b", "act", 1),
      instance("g", "act", 9),
    ]);
    const byNode = definitionsByNode(graph, catalog);
    const base = { source: "a", target: "b", sourceHandle: "out", targetHandle: "in" };

    expect(isConnectionValid(base, byNode)).toBe(true);
    expect(isConnectionValid({ ...base, sourceHandle: null }, byNode)).toBe(false);
    expect(isConnectionValid({ ...base, targetHandle: null }, byNode)).toBe(false);
    expect(isConnectionValid({ ...base, target: "a" }, byNode)).toBe(false);
    expect(isConnectionValid({ ...base, source: "g" }, byNode)).toBe(false);
    expect(isConnectionValid({ ...base, target: "g" }, byNode)).toBe(false);
  });

  it("refuses a connection between mismatched port shapes", () => {
    const mismatched = def({
      id: "other",
      ports: [{ id: "in", label: "In", kind: "input", schema: OBJECT_B }],
    });
    const catalog = buildCatalogMap([ACTION, mismatched]);
    const graph = graphOf([instance("a", "act", 1), instance("b", "other", 1)]);
    const byNode = definitionsByNode(graph, catalog);
    expect(
      isConnectionValid(
        { source: "a", target: "b", sourceHandle: "out", targetHandle: "in" },
        byNode,
      ),
    ).toBe(false);
  });
});
