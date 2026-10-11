import { describe, expect, it } from "vitest";

import type {
  JsonSchema,
  NodeDefinition,
  NodeInstance,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { DEBUG_ECHO, DEBUG_RELAY } from "@/components/workflows/validation/fixtures";

import {
  autoBindings,
  buildCatalogMap,
  definitionsByNode,
  edgeVariant,
  ERROR_PORT_ID,
  isConnectionValid,
  isErrorPort,
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

  it("flags the selected nodes and edges, and none by default", () => {
    const catalog = buildCatalogMap([ACTION]);
    const graph = graphOf(
      [instance("a", "act", 1), instance("b", "act", 1)],
      [
        {
          id: "e1",
          source_node_id: "a",
          source_port: "out",
          target_node_id: "b",
          target_port: "in",
        },
      ],
    );
    const byNode = definitionsByNode(graph, catalog);

    expect(toFlowNodes(graph, byNode, false).map((node) => node.selected)).toEqual([false, false]);
    expect(toFlowEdges(graph, byNode).map((edge) => edge.selected)).toEqual([false]);

    expect(toFlowNodes(graph, byNode, false, new Set(["b"])).map((node) => node.selected)).toEqual([
      false,
      true,
    ]);
    expect(toFlowEdges(graph, byNode, new Set(["e1"])).map((edge) => edge.selected)).toEqual([
      true,
    ]);
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

  describe("autoBindings", () => {
    const catalog = buildCatalogMap([DEBUG_ECHO, DEBUG_RELAY, ACTION, CONTROL]);
    const graph = graphOf([
      instance("e", "debug.echo", 1),
      instance("r", "debug.relay", 1),
      instance("a", "act", 1),
      instance("c", "ctrl", 1),
      instance("g", "ghost", 1),
    ]);
    const definitions = definitionsByNode(graph, catalog);
    const link = (source: string, sourceHandle: string, target: string, targetHandle: string) => ({
      source,
      sourceHandle,
      target,
      targetHandle,
    });
    const echoedFrom = (field: string) => ({
      target_node_id: "r",
      target_field: field,
      source: { kind: "node_output", node_id: "e", port: "out", field_path: [field] },
    });

    it("binds every field of a same-shaped target to the source's field of that name", () => {
      expect(autoBindings(link("e", "out", "r", "in"), graph, definitions)).toEqual([
        echoedFrom("echoed"),
        echoedFrom("received_at"),
      ]);
    });

    it("leaves a field that is already bound alone", () => {
      const bound: WorkflowGraph = {
        ...graph,
        bindings: [
          {
            target_node_id: "r",
            target_field: "echoed",
            source: { kind: "literal", value: "typed by hand" },
          },
          // Another node's binding of a same-named field is not this node's.
          {
            target_node_id: "e",
            target_field: "received_at",
            source: { kind: "literal", value: "x" },
          },
        ],
      };
      expect(autoBindings(link("e", "out", "r", "in"), bound, definitions)).toEqual([
        echoedFrom("received_at"),
      ]);
    });

    it("implies nothing when either end is a control port", () => {
      expect(autoBindings(link("e", "out", "c", "in"), graph, definitions)).toEqual([]);
      expect(autoBindings(link("c", "then", "r", "in"), graph, definitions)).toEqual([]);
    });

    it("implies nothing when the shapes differ, since which field feeds which is a choice", () => {
      expect(autoBindings(link("r", "out", "r", "in"), graph, definitions)).toEqual([]);
    });

    it("reads the one list a source hands on into the one list a target works on", () => {
      const listing = def({
        id: "list",
        ports: [
          {
            id: "out",
            label: "Out",
            kind: "output",
            schema: {
              type: "object",
              properties: {
                records: { type: "array", items: {} },
                total: { type: "integer" },
              },
            },
          },
        ],
      });
      const takes = {
        type: "object",
        properties: {
          items: { anyOf: [{ type: "array", items: {} }, { type: "null" }] },
          note: { type: "string" },
        },
      };
      const filtering = def({
        id: "filter",
        input_schema: takes,
        // As the catalog serves it: an input that carries nothing, read by binding.
        ports: [{ id: "in", label: "In", kind: "input", schema: null }],
      });
      const twoLists = def({
        id: "two",
        ports: [
          {
            id: "out",
            label: "Out",
            kind: "output",
            schema: {
              type: "object",
              properties: { a: { type: "array" }, b: { type: "array" } },
            },
          },
        ],
      });
      const lists = graphOf([
        instance("l", "list", 1),
        instance("f", "filter", 1),
        instance("t", "two", 1),
      ]);
      const known = definitionsByNode(lists, buildCatalogMap([listing, filtering, twoLists]));
      expect(autoBindings(link("l", "out", "f", "in"), lists, known)).toEqual([
        {
          target_node_id: "f",
          target_field: "items",
          source: { kind: "node_output", node_id: "l", port: "out", field_path: ["records"] },
        },
      ]);
      // Two lists to choose from, or the list already given, is left to the builder.
      expect(autoBindings(link("t", "out", "f", "in"), lists, known)).toEqual([]);
      // A source declaring no fields, or one whose field is a bare `true`, hands on no list.
      const bare = def({
        id: "bare-out",
        ports: [
          { id: "out", label: "Out", kind: "output", schema: { type: "object", title: "Any" } },
        ],
      });
      const loose = def({
        id: "loose-out",
        ports: [
          {
            id: "out",
            label: "Out",
            kind: "output",
            schema: { type: "object", properties: { extra: true } },
          },
        ],
      });
      const odd = graphOf([
        instance("b", "bare-out", 1),
        instance("o", "loose-out", 1),
        instance("f", "filter", 1),
      ]);
      const oddKnown = definitionsByNode(odd, buildCatalogMap([bare, loose, filtering]));
      expect(autoBindings(link("b", "out", "f", "in"), odd, oddKnown)).toEqual([]);
      expect(autoBindings(link("o", "out", "f", "in"), odd, oddKnown)).toEqual([]);
      const given: WorkflowGraph = {
        ...lists,
        bindings: [
          { target_node_id: "f", target_field: "items", source: { kind: "literal", value: [] } },
        ],
      };
      expect(autoBindings(link("l", "out", "f", "in"), given, known)).toEqual([]);
    });

    it("binds only fields of the target's input schema", () => {
      // `act` declares the shape on its ports but takes no input schema.
      expect(autoBindings(link("a", "out", "a", "in"), graph, definitions)).toEqual([]);
    });

    it("implies nothing for an unresolved node, a missing handle or an unknown port", () => {
      expect(autoBindings(link("g", "out", "r", "in"), graph, definitions)).toEqual([]);
      expect(autoBindings(link("e", "out", "g", "in"), graph, definitions)).toEqual([]);
      expect(
        autoBindings({ ...link("e", "out", "r", "in"), sourceHandle: null }, graph, definitions),
      ).toEqual([]);
      expect(
        autoBindings({ ...link("e", "out", "r", "in"), targetHandle: null }, graph, definitions),
      ).toEqual([]);
      expect(autoBindings(link("e", "nope", "r", "in"), graph, definitions)).toEqual([]);
      expect(autoBindings(link("e", "out", "r", "nope"), graph, definitions)).toEqual([]);
    });

    it("implies nothing when a port's schema declares no properties", () => {
      const bare = def({
        id: "bare",
        input_schema: { type: "object", title: "Bare" },
        ports: [
          { id: "in", label: "In", kind: "input", schema: { type: "object", title: "Bare" } },
          { id: "out", label: "Out", kind: "output", schema: { type: "object", title: "Bare" } },
        ],
      });
      const bareGraph = graphOf([instance("b", "bare", 1)]);
      const bareDefinitions = definitionsByNode(bareGraph, buildCatalogMap([bare]));
      expect(autoBindings(link("b", "out", "b", "in"), bareGraph, bareDefinitions)).toEqual([]);
    });
  });
});
