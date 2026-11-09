import { describe, expect, it } from "vitest";

import type {
  NodeDefinition,
  NodeInstance,
  Port,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { clearOf, loopStepsOf, planInsertion, withLiveScopes } from "./insertion";
import { NODE_HEIGHT, NODE_WIDTH } from "./node-size";

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
const LOOP = def("control.foreach", [port("in", "input", null), port("done", "output", null)], {
  kind: "control",
});
const ITEM = def("loop.item", [port("out", "output")], {
  kind: "control",
  input_schema: null,
  loop_body_only: true,
});
const RESULT = def("loop.yield", [port("in", "input", null)], {
  kind: "control",
  loop_body_only: true,
});

function node(
  id: string,
  definition: NodeDefinition,
  x = 0,
  y = 0,
  scopeId: string | null = null,
): NodeInstance {
  return {
    id,
    definition_id: definition.id,
    definition_version: 1,
    config: {},
    layout: { x, y },
    ...(scopeId !== null ? { scope_id: scopeId } : {}),
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

const BY_ID = {
  "core.input": INPUT,
  step: STEP,
  sink: SINK,
  "control.foreach": LOOP,
  "loop.item": ITEM,
  "loop.yield": RESULT,
};

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
    const taken = [node("a", STEP, 0, 0), node("b", STEP, 0, NODE_HEIGHT + 24)];
    expect(clearOf([], { x: 5, y: 5 })).toEqual({ x: 5, y: 5 });
    expect(clearOf(taken, { x: 0, y: 0 })).toEqual({ x: 0, y: 2 * (NODE_HEIGHT + 24) });
  });

  it("clears the tallest common card: a step is never dropped within reach of an Approval", () => {
    // Approval: 24 padding + 14 label + 20 name + 16 summary + 2 border + 22 band, and its
    // two labelled ports (47) taller than the text beside them - about 129 px.
    const APPROVAL = 129;
    const approval = [node("a", STEP, 0, 0)];
    const placed = clearOf(approval, { x: 0, y: APPROVAL - 1 }, () => ({
      width: NODE_WIDTH,
      height: APPROVAL,
    }));
    expect(placed.y - APPROVAL).toBeGreaterThan(0);
  });

  it("clears a resized step by its own width and height, not the default", () => {
    const wide = { ...node("w", STEP, 0, 0), layout: { x: 0, y: 0, width: 500, height: 200 } };
    // A column over, but still inside the wide card: pushed under it.
    expect(clearOf([wide], { x: 400, y: 10 })).toEqual({ x: 400, y: 224 });
    // Beyond its right edge and the gap there: free.
    expect(clearOf([wide], { x: 500 + 80, y: 10 })).toEqual({ x: 580, y: 10 });
    // A taller new card reaches down into a step below it.
    const below = node("b", STEP, 0, 100);
    expect(clearOf([below], { x: 0, y: 0 }, undefined, { width: NODE_WIDTH, height: 150 }).y).toBe(
      100 + NODE_HEIGHT + 24,
    );
  });

  it("keeps the vertical gap too: a step is never dropped a few pixels from one below it", () => {
    // 100 px down is 12 px clear of a default card dropped at 0, inside the 24 px gap.
    const below = node("b", STEP, 0, 100);
    expect(clearOf([below], { x: 0, y: 0 })).toEqual({ x: 0, y: 100 + NODE_HEIGHT + 24 });
  });

  it("settles anyway once it has looked far enough down", () => {
    const column = Array.from({ length: 60 }, (_, i) =>
      node(`n${i}`, STEP, 0, i * (NODE_HEIGHT + 24)),
    );
    expect(clearOf(column, { x: 0, y: 0 }).y).toBe(40 * (NODE_HEIGHT + 24));
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

  it("lands beyond the right edge of a step somebody widened", () => {
    const wide = { ...node("a", STEP), layout: { x: 0, y: 0, width: 500, height: 300 } };
    const planned = plan(graph([wide]), STEP, { selectedIds: ["a"] });
    expect(planned.node.layout).toEqual({ x: 500 + 80, y: 0 });
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
    expect(planned.node.layout).toEqual({ x: RIGHT, y: 76 + 24 });
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

  it("puts every step added inside a loop body in that body, after its loop item", () => {
    const fresh = graph([
      node("f", LOOP),
      node("i", ITEM, 0, 0, "f"),
      node("r", RESULT, 900, 0, "f"),
    ]);
    const first = plan(fresh, STEP, { scopePath: ["f"] });
    expect(first.node.scope_id).toBe("f");
    expect(first.edge).toMatchObject({ source_node_id: "i", source_port: "out" });

    const withBody = graph(
      [node("f", LOOP), node("i", ITEM, 0, 0, "f"), node("b", STEP, RIGHT, 0, "f")],
      [edge("i", "out", "b")],
    );
    const dropped = plan(withBody, STEP, { scopePath: ["f"], dropAt: { x: 500, y: 300 } });
    expect(dropped.edge).toMatchObject({ source_node_id: "b" });
    expect(dropped.node).toMatchObject({ scope_id: "f", layout: { x: 500, y: 300 } });
    // A starting step inside a body is neither the start nor wired to it.
    expect(plan(withBody, INPUT, { scopePath: ["f"] })).toMatchObject({
      node: { scope_id: "f" },
      edge: null,
      becomesEntry: false,
    });
  });

  it("never wires a step from the loop itself, even when every way out in the body is taken", () => {
    const full = graph(
      [node("f", LOOP), node("i", ITEM, 0, 0, "f"), node("r", RESULT, RIGHT, 0, "f")],
      [edge("i", "out", "r")],
    );
    const planned = plan(full, STEP, { scopePath: ["f"] });
    expect(planned.edge).toBeNull();
    expect(planned.node.scope_id).toBe("f");
  });

  it("puts a new loop's item and result steps inside it, and only a loop's", () => {
    const loopSteps = { item: ITEM, result: RESULT };
    const added = plan(graph([node("a", INPUT)]), LOOP, { loopSteps });
    expect(added.companions).toHaveLength(2);
    expect(added.companions).toEqual([
      expect.objectContaining({ definition_id: "loop.item", scope_id: "new" }),
      expect.objectContaining({ definition_id: "loop.yield", scope_id: "new" }),
    ]);
    expect(plan(graph([node("a", INPUT)]), STEP, { loopSteps }).companions).toBeUndefined();
    expect(plan(graph([node("a", INPUT)]), LOOP).companions).toBeUndefined();
  });

  it("puts a new loop's item and result steps inside it when it is dropped onto a wire", () => {
    const line = graph([node("a", INPUT), node("b", STEP, 640, 0)], [edge("a", "out", "b")]);
    const split = plan(line, LOOP, {
      between: edge("a", "out", "b"),
      loopSteps: { item: ITEM, result: RESULT },
    });
    expect(split.split).toBeDefined();
    expect(split.companions?.map((step) => step.scope_id)).toEqual(["new", "new"]);
  });

  it("takes the catalog's newest loop item and result, and none when either is missing", () => {
    const newer = { ...ITEM, version: 2 };
    expect(loopStepsOf([ITEM, newer, RESULT])).toEqual({ item: newer, result: RESULT });
    expect(loopStepsOf([newer, ITEM, RESULT])).toEqual({ item: newer, result: RESULT });
    expect(loopStepsOf([ITEM])).toBeUndefined();
  });

  it("leaves a step added at the top level in no loop", () => {
    expect(plan(graph([node("a", INPUT)]), STEP).node.scope_id).toBeUndefined();
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

  it("adds another trigger without replacing the existing start", () => {
    const g = graph(
      [node("m", MANUAL, 40, 60), node("a", STEP, RIGHT, 0)],
      [edge("m", "out", "a")],
    );
    expect(planWith(g, WEBHOOK)).toMatchObject({
      node: { id: "new", definition_id: "trigger.webhook", layout: { x: 40, y: 172 } },
      edge: null,
      bindings: [],
      becomesEntry: false,
      replaces: null,
    });
    expect(planWith(g, WEBHOOK, { dropAt: { x: 7, y: 8 } }).node.layout).toEqual({ x: 7, y: 8 });
  });

  it("places an independent trigger clear of the existing large trigger", () => {
    const old = { ...node("m", MANUAL, 40, 60), layout: { x: 40, y: 60, width: 400, height: 200 } };
    const g = graph([old, node("a", STEP, RIGHT, 0)], [edge("m", "out", "a")]);
    expect(planWith(g, WEBHOOK).node.layout).toEqual({ x: 40, y: 284 });
  });

  it("keeps the default when adding a third independent start", () => {
    const g = graph([node("a", STEP), node("m", MANUAL, 400, 0)], [], "a");
    expect(planWith(g, WEBHOOK)).toMatchObject({ replaces: null, becomesEntry: false });
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
  it("derives the loop bodies from the loop each step names", () => {
    const g = graph([node("f", LOOP), node("b", STEP, 0, 0, "f")]);
    const [scope] = withLiveScopes(g, definitionsOf(g, BY_ID)).scopes;
    expect(scope).toMatchObject({ scope_node_id: "f", body_node_ids: ["b"] });
  });
});

describe("a step put into a connection", () => {
  const line = () =>
    graph([node("a", INPUT, 0, 0), node("b", STEP, 640, 0)], [edge("a", "out", "b")]);

  it("goes halfway along it, fed by its source and feeding where it led", () => {
    const g = line();
    const planned = plan(g, STEP, { between: g.edges[0] });

    expect(planned.node.layout).toEqual({ x: 320, y: 0 });
    expect(planned.edge).toMatchObject({ source_node_id: "a", target_node_id: "new" });
    expect(planned.split?.edgeId).toBe("a-b");
    expect(planned.split?.tail).toMatchObject({
      source_node_id: "new",
      source_port: "out",
      target_node_id: "b",
      target_port: "in",
    });
  });

  it("ends the flow at a step with nowhere to go on to", () => {
    const g = line();
    const END = def("end", [port("in", "input")]);
    expect(plan(g, END, { between: g.edges[0] }).split?.tail).toBeNull();
  });

  it("is added the ordinary way when the connection cannot feed it", () => {
    const g = line();
    expect(plan(g, SINK, { between: g.edges[0] }).split).toBeUndefined();
    expect(
      plan(g, STEP, { between: { ...g.edges[0]!, source_node_id: "gone" } }).split,
    ).toBeUndefined();
  });
});
