import { describe, expect, it } from "vitest";

import type {
  NodeDefinition,
  NodeInstance,
  Port,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { clearOf, NODE_HEIGHT, NODE_WIDTH, planInsertion, withLiveScopes } from "./insertion";

const OBJECT = { type: "object", properties: { text: { type: "string" } } };

function port(id: string, kind: Port["kind"], schema: unknown = OBJECT): Port {
  return { id, label: id, kind, schema } as Port;
}

function def(id: string, ports: Port[], overrides: Partial<NodeDefinition> = {}): NodeDefinition {
  return {
    id,
    version: 1,
    name: id,
    category: "c",
    description: "",
    kind: "action",
    config_schema: null,
    input_schema: { type: "object", properties: { text: { type: "string" } } },
    output_schema: null,
    ports,
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
    ...overrides,
  };
}

const INPUT = def("core.input", [port("out", "output")], { input_schema: null });
const STEP = def("step", [port("in", "input"), port("out", "output")]);
const SINK = def("sink", [port("in", "input", { type: "array" })]);
const LOOP = def(
  "control.foreach",
  [port("in", "input", null), port("body", "output", null), port("done", "output", null)],
  { kind: "control" },
);

function node(id: string, definition: NodeDefinition, x = 0, y = 0): NodeInstance {
  return {
    id,
    definition_id: definition.id,
    definition_version: 1,
    config: {},
    layout: { x, y },
  };
}

function edge(source: string, sourcePort: string, target: string): WorkflowEdge {
  return {
    id: `${source}-${target}`,
    source_node_id: source,
    source_port: sourcePort,
    target_node_id: target,
    target_port: "in",
  };
}

function graph(nodes: NodeInstance[], edges: WorkflowEdge[] = [], entry = nodes[0]?.id ?? "") {
  const value: WorkflowGraph = { entry_node_id: entry, nodes, edges, bindings: [], scopes: [] };
  return value;
}

function definitionsOf(g: WorkflowGraph, byId: Record<string, NodeDefinition>) {
  return new Map<string, NodeDefinition | null>(
    g.nodes.map((item) => [item.id, byId[item.definition_id] ?? null]),
  );
}

const WEBHOOK = def("trigger.webhook", [port("out", "output")], {
  input_schema: null,
  category: "triggers",
});
const MANUAL = def("core.input", [port("out", "output")], {
  input_schema: null,
  category: "triggers",
});

const BY_ID = { "core.input": INPUT, step: STEP, sink: SINK, "control.foreach": LOOP };

function plan(
  g: WorkflowGraph,
  definition: NodeDefinition,
  extra: Partial<Parameters<typeof planInsertion>[0]> = {},
) {
  return planInsertion({
    graph: g,
    definitions: definitionsOf(g, BY_ID),
    scopePath: [],
    selectedIds: [],
    definition,
    id: "new",
    ...extra,
  });
}

const RIGHT = NODE_WIDTH + 80;

describe("clearOf", () => {
  it("keeps a free spot, and moves an occupied one down a row until it is free", () => {
    const taken = [node("a", STEP, 0, 0), node("b", STEP, 0, NODE_HEIGHT + 32)];
    expect(clearOf([], { x: 5, y: 5 })).toEqual({ x: 5, y: 5 });
    expect(clearOf(taken, { x: 0, y: 0 })).toEqual({ x: 0, y: 2 * (NODE_HEIGHT + 32) });
  });

  it("settles anyway once it has looked far enough down", () => {
    const column = Array.from({ length: 60 }, (_, i) =>
      node(`n${i}`, STEP, 0, i * (NODE_HEIGHT + 32)),
    );
    expect(clearOf(column, { x: 0, y: 0 }).y).toBe(40 * (NODE_HEIGHT + 32));
  });
});

describe("planInsertion", () => {
  it("puts the first step of an empty graph at the origin and makes it the start", () => {
    const planned = plan(graph([]), STEP);
    expect(planned).toMatchObject({
      node: { id: "new", layout: { x: 0, y: 0 } },
      edge: null,
      becomesEntry: true,
    });
  });

  it("wires a step after the selected one, with the bindings a same-shaped wire implies", () => {
    const g = graph([node("a", STEP), node("b", STEP, 0, 400)]);
    const planned = plan(g, STEP, { selectedIds: ["a"] });
    expect(planned.node.layout).toEqual({ x: RIGHT, y: 0 });
    expect(planned.edge).toMatchObject({
      source_node_id: "a",
      source_port: "out",
      target_node_id: "new",
      target_port: "in",
    });
    expect(planned.bindings).toEqual([
      expect.objectContaining({ target_node_id: "new", target_field: "text" }),
    ]);
    expect(planned.becomesEntry).toBe(false);
  });

  it("appends to the end of the flow when nothing is selected, or the selection's output is taken", () => {
    const g = graph([node("a", STEP), node("b", STEP, RIGHT, 0)], [edge("a", "out", "b")]);
    expect(plan(g, STEP).edge?.source_node_id).toBe("b");
    expect(plan(g, STEP, { selectedIds: ["a"] }).edge?.source_node_id).toBe("b");
    expect(plan(g, STEP, { selectedIds: ["a", "b"] }).node.layout).toEqual({ x: 2 * RIGHT, y: 0 });
  });

  it("adds after the output it was asked for, even one already wired", () => {
    const g = graph([node("a", STEP), node("b", STEP, RIGHT, 0)], [edge("a", "out", "b")]);
    const planned = plan(g, STEP, { from: { nodeId: "a", portId: "out" } });
    expect(planned.edge).toMatchObject({ source_node_id: "a", source_port: "out" });
    // Clear of `b`, which already sits where it would have gone.
    expect(planned.node.layout).toEqual({ x: RIGHT, y: NODE_HEIGHT + 32 });
  });

  it("places a step asked for after a node that is gone after the rightmost one, unwired", () => {
    const g = graph([node("a", STEP)]);
    const planned = plan(g, STEP, { from: { nodeId: "missing", portId: "out" } });
    expect(planned).toMatchObject({ edge: null, node: { layout: { x: RIGHT, y: 0 } } });
  });

  it("leaves a step dropped at the top level where it fell, unwired", () => {
    const g = graph([node("a", STEP)]);
    const planned = plan(g, STEP, { dropAt: { x: 900, y: 40 }, selectedIds: ["a"] });
    expect(planned).toMatchObject({ edge: null, node: { layout: { x: 900, y: 40 } } });
  });

  it("does not wire ports whose shapes differ", () => {
    const g = graph([node("a", STEP)]);
    expect(plan(g, SINK, { selectedIds: ["a"] }).edge).toBeNull();
  });

  it("puts a starting step before the current start, wired into it, as the new start", () => {
    const g = graph([node("a", STEP, 400, 80)]);
    const planned = plan(g, INPUT);
    expect(planned.node.layout).toEqual({ x: 400 - RIGHT, y: 80 });
    expect(planned.edge).toMatchObject({ source_node_id: "new", target_node_id: "a" });
    expect(planned.becomesEntry).toBe(true);
  });

  it("keeps an existing starting step the start, and a starting step dropped where it fell", () => {
    const g = graph([node("i", INPUT)]);
    const planned = plan(g, INPUT, { dropAt: { x: 10, y: 600 } });
    expect(planned).toMatchObject({
      edge: null,
      becomesEntry: false,
      node: { layout: { x: 10, y: 600 } },
    });
    expect(plan(graph([]), INPUT)).toMatchObject({
      becomesEntry: true,
      node: { layout: { x: 0, y: 0 } },
    });
  });

  it("wires every step added inside a loop body, so it stays in the body", () => {
    const loopOnly = graph([node("f", LOOP)]);
    const inEmptyBody = plan(loopOnly, STEP, { scopePath: ["f"] });
    expect(inEmptyBody.edge).toMatchObject({ source_node_id: "f", source_port: "body" });

    const withBody = graph([node("f", LOOP), node("b", STEP, RIGHT, 0)], [edge("f", "body", "b")]);
    const dropped = plan(withBody, STEP, { scopePath: ["f"], dropAt: { x: 500, y: 300 } });
    expect(dropped.edge).toMatchObject({ source_node_id: "b" });
    expect(dropped.node.layout).toEqual({ x: 500, y: 300 });
    // A starting step inside a body is neither the start nor wired to it.
    expect(plan(withBody, INPUT, { scopePath: ["f"] })).toMatchObject({
      edge: null,
      becomesEntry: false,
    });
  });

  it("adds a step inside a body of a loop that no longer exists unwired", () => {
    const g = graph([node("a", STEP)]);
    expect(plan(g, STEP, { scopePath: ["gone"] }).edge).toBeNull();
  });

  it("passes over steps whose type the catalog no longer has, and picks the rightmost end", () => {
    const g = graph(
      [node("ghost", def("gone", []), 900, 0), node("right", STEP, 600, 0), node("left", STEP)],
      [],
      "ghost",
    );
    const planned = plan(g, STEP, { selectedIds: ["ghost"] });
    expect(planned.edge?.source_node_id).toBe("right");
    // A starting step before a start the catalog cannot describe is not wired to it.
    expect(plan(g, INPUT)).toMatchObject({ edge: null, becomesEntry: false });
    // Inside a loop the catalog cannot describe there is no body port to start from.
    const unknownLoop = graph([node("f", def("control.gone", []))]);
    expect(plan(unknownLoop, STEP, { scopePath: ["f"] }).edge).toBeNull();
  });

  it("takes a fresh id when it is given none", () => {
    const planned = planInsertion({
      graph: graph([]),
      definitions: new Map(),
      scopePath: [],
      selectedIds: [],
      definition: STEP,
    });
    expect(planned.node.id).toMatch(/[0-9a-f-]{36}/);
  });
});

describe("planInsertion with triggers", () => {
  const TRIGGERS = { ...BY_ID, "core.input": MANUAL, "trigger.webhook": WEBHOOK };
  const planWith = (g: WorkflowGraph, definition: NodeDefinition, extra = {}) =>
    planInsertion({
      graph: g,
      definitions: definitionsOf(g, TRIGGERS),
      scopePath: [],
      selectedIds: [],
      definition,
      id: "new",
      ...extra,
    });

  it("replaces the workflow's trigger in its place, as the start", () => {
    const g = graph(
      [node("m", MANUAL, 40, 60), node("a", STEP, RIGHT, 0)],
      [edge("m", "out", "a")],
    );
    expect(planWith(g, WEBHOOK)).toMatchObject({
      node: { id: "new", definition_id: "trigger.webhook", layout: { x: 40, y: 60 } },
      edge: null,
      bindings: [],
      becomesEntry: true,
      replaces: "m",
    });
    expect(planWith(g, WEBHOOK, { dropAt: { x: 7, y: 8 } }).node.layout).toEqual({ x: 7, y: 8 });
  });

  it("replaces a trigger that is not the start without making the new one the start", () => {
    const g = graph([node("a", STEP), node("m", MANUAL, 400, 0)], [], "a");
    expect(planWith(g, WEBHOOK)).toMatchObject({ replaces: "m", becomesEntry: false });
  });

  it("puts a first trigger before the start, as any starting step goes", () => {
    const g = graph([node("a", STEP, 400, 0)]);
    expect(planWith(g, WEBHOOK)).toMatchObject({
      replaces: null,
      becomesEntry: true,
      edge: expect.objectContaining({ source_node_id: "new", target_node_id: "a" }),
    });
  });
});

describe("withLiveScopes", () => {
  it("derives the loop bodies from the wires as they are now", () => {
    const g = graph([node("f", LOOP), node("b", STEP)], [edge("f", "body", "b")]);
    const [scope] = withLiveScopes(g, definitionsOf(g, BY_ID)).scopes;
    expect(scope).toMatchObject({ scope_node_id: "f", body_node_ids: ["b"] });
  });
});
