/**
 * Run conditions, mirrored from `backend/tests/test_workflow_joins.py`: the same graphs
 * and the same answers, so a change to one analysis fails the other's tests. Each case
 * asserts which steps can run together, what precedes the join, and whether the wires
 * into it run whenever it does.
 */

import { describe, expect, it } from "vitest";

import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { echo, edge, graph, makeCatalog, makeDefinition, node, port } from "./fixtures";
import {
  MAX_TERMS,
  analyse,
  anyPairRunsTogether,
  canRunTogether,
  covers,
  mayHoldTogether,
  runsWhenever,
  wireCondition,
  wireRunsWhenever,
  type GraphAnalysis,
  type JoinWire,
} from "./joins";
import { rule7NoCycles } from "./rules";
import { deriveScopes, nodeScopeMap, resolveDefinitions } from "./topology";

const IN = port("in", "input", null);
const OUT = port("out", "output", null);

const CATALOG = makeCatalog([
  makeDefinition({ id: "debug.echo", ports: [IN, OUT] }),
  makeDefinition({
    id: "logic.if",
    kind: "control",
    exclusive_branches: true,
    ports: [IN, port("true", "output", null), port("false", "output", null)],
  }),
  makeDefinition({
    id: "logic.switch",
    kind: "control",
    exclusive_branches: true,
    ports: [IN, port("otherwise", "output", null)],
  }),
  makeDefinition({ id: "logic.split", kind: "control", ports: [IN] }),
  makeDefinition({
    id: "error.handle",
    kind: "control",
    exclusive_branches: true,
    ports: [IN, port("default", "output", null)],
  }),
  makeDefinition({ id: "loop.item", kind: "control", ports: [IN, OUT] }),
  makeDefinition({ id: "loop.yield", kind: "control", ports: [IN, OUT] }),
  makeDefinition({
    id: "control.foreach",
    kind: "control",
    ports: [IN, port("body", "output", null), port("done", "output", null)],
  }),
]);

function step(id: string, routed = false): NodeInstance {
  const instance = echo(id);
  return routed ? { ...instance, policy: { on_error: "route" } } : instance;
}
const ifNode = (id: string) => node(id, "logic.if", { condition: "value" });
const switchNode = (id: string, ...names: string[]) =>
  node(id, "logic.switch", { rules: names.map((name) => ({ name, condition: "value" })) });
const splitNode = (id: string, ...names: string[]) =>
  node(id, "logic.split", { branches: names.map((name) => ({ name })) });

type Wiring = [string, string, string];

function build(nodes: NodeInstance[], wiring: Wiring[]): WorkflowGraph {
  return graph({
    entry: (nodes[0] as NodeInstance).id,
    nodes,
    edges: wiring.map(([source, sourcePort, target], index) =>
      edge(`e${index}`, source, sourcePort, target, "in"),
    ),
  });
}

function analyseGraph(g: WorkflowGraph): GraphAnalysis {
  const definitions = resolveDefinitions(g, CATALOG);
  const scopes = deriveScopes(g, definitions);
  const nodeScope = nodeScopeMap(scopes);
  return analyse(g, definitions, nodeScope, rule7NoCycles(g, nodeScope).order !== null);
}

const start = () => step("start");

function wiresTogether(a: GraphAnalysis, join = "J"): boolean {
  return anyPairRunsTogether(a, join);
}

function wiresWhenever(a: GraphAnalysis, join = "J"): Record<string, boolean> {
  return Object.fromEntries(
    (a.incoming.get(join) ?? []).map((wire) => [
      `${wire.sourceNodeId}.${wire.sourcePort}`,
      wireRunsWhenever(a, join, wire),
    ]),
  );
}

const precedes = (a: GraphAnalysis, join = "J"): Set<string> => a.precede.get(join) as Set<string>;
const together = (a: GraphAnalysis, first: string, second: string): boolean =>
  canRunTogether(a, first, second);
const isAlways = (a: GraphAnalysis, id: string): boolean => {
  const condition = a.conditions.get(id) as { terms: Set<string>[] };
  return condition.terms.length === 1 && condition.terms[0]?.size === 0;
};

const split2 = () =>
  build(
    [start(), splitNode("S", "a", "b"), step("A"), step("B"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "a", "A"],
      ["S", "b", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );
const ifElse = () =>
  build(
    [start(), ifNode("I"), step("A"), step("B"), step("J")],
    [
      ["start", "out", "I"],
      ["I", "true", "A"],
      ["I", "false", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );
const mixed = () =>
  build(
    [start(), ifNode("I"), step("A"), step("B"), step("C"), step("J")],
    [
      ["start", "out", "I"],
      ["I", "true", "A"],
      ["I", "true", "B"],
      ["I", "false", "C"],
      ["A", "out", "J"],
      ["B", "out", "J"],
      ["C", "out", "J"],
    ],
  );
const nested = () =>
  build(
    [start(), splitNode("S", "a", "b"), ifNode("I"), step("A"), step("B"), step("C"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "a", "I"],
      ["I", "true", "A"],
      ["I", "false", "B"],
      ["S", "b", "C"],
      ["A", "out", "J"],
      ["B", "out", "J"],
      ["C", "out", "J"],
    ],
  );
const common = () =>
  build(
    [start(), ifNode("I"), step("K"), step("A"), step("J")],
    [
      ["start", "out", "I"],
      ["I", "true", "K"],
      ["I", "false", "K"],
      ["K", "out", "J"],
      ["I", "true", "A"],
      ["A", "out", "J"],
    ],
  );
const routedLeg = () =>
  build(
    [
      start(),
      splitNode("S", "a", "b"),
      step("A", true),
      node("H", "error.handle", {}),
      step("B"),
      step("J"),
    ],
    [
      ["start", "out", "S"],
      ["S", "a", "A"],
      ["A", "out", "J"],
      ["A", "error", "H"],
      ["H", "default", "J"],
      ["S", "b", "B"],
      ["B", "out", "J"],
    ],
  );
const fanoutPartial = () =>
  build(
    [start(), switchNode("W", "r"), step("A"), ifNode("B"), step("J")],
    [
      ["start", "out", "W"],
      ["W", "r", "A"],
      ["A", "out", "J"],
      ["W", "r", "B"],
      ["B", "true", "J"],
    ],
  );
const straight = () =>
  build(
    [start(), switchNode("S", "p", "q"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "p", "J"],
      ["S", "q", "J"],
    ],
  );
const reachedFromBothPorts = () =>
  build(
    [start(), ifNode("X"), step("P"), step("T"), step("J")],
    [
      ["start", "out", "X"],
      ["X", "true", "P"],
      ["P", "out", "T"],
      ["X", "false", "T"],
      ["T", "out", "J"],
      ["P", "out", "J"],
    ],
  );
const skippedByOnePort = () =>
  build(
    [start(), ifNode("X"), step("t"), step("Y"), step("T"), step("A"), step("J")],
    [
      ["start", "out", "X"],
      ["X", "true", "t"],
      ["X", "false", "Y"],
      ["Y", "out", "t"],
      ["t", "out", "T"],
      ["X", "true", "A"],
      ["A", "out", "J"],
      ["T", "out", "J"],
    ],
  );
const outputsAfterBothPorts = () =>
  build(
    [start(), ifNode("X"), step("P"), step("T"), step("O1"), step("O2")],
    [
      ["start", "out", "X"],
      ["X", "true", "P"],
      ["P", "out", "O1"],
      ["P", "out", "T"],
      ["X", "false", "T"],
      ["T", "out", "O2"],
    ],
  );
const nestedWithSharedElse = () =>
  build(
    [start(), ifNode("X"), ifNode("Y"), step("A"), step("T"), step("J")],
    [
      ["start", "out", "X"],
      ["X", "true", "Y"],
      ["Y", "true", "A"],
      ["Y", "false", "T"],
      ["X", "false", "T"],
      ["A", "out", "J"],
      ["T", "out", "J"],
    ],
  );
const switchSharingAStep = () =>
  build(
    [start(), switchNode("S", "a", "b"), step("s"), step("C"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "a", "s"],
      ["S", "b", "s"],
      ["S", "otherwise", "C"],
      ["s", "out", "J"],
      ["C", "out", "J"],
    ],
  );
const unwiredOtherwise = () =>
  build(
    [start(), switchNode("S", "r1", "r2"), step("A"), step("B"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "r1", "A"],
      ["S", "r2", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );
const switchFullyMerged = () =>
  build(
    [start(), switchNode("S", "r1", "r2"), step("A1"), step("A2"), step("A3"), step("J")],
    [
      ["start", "out", "S"],
      ["S", "r1", "A1"],
      ["S", "r2", "A2"],
      ["S", "otherwise", "A3"],
      ["A1", "out", "J"],
      ["A2", "out", "J"],
      ["A3", "out", "J"],
    ],
  );
const routedErrorPort = () =>
  build(
    [start(), step("R", true), step("A"), node("H", "error.handle", {}), step("B"), step("J")],
    [
      ["start", "out", "R"],
      ["R", "out", "A"],
      ["R", "error", "H"],
      ["H", "default", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );

function loopGraph(parallel = true): WorkflowGraph {
  const nodes = [
    start(),
    node("F", "control.foreach"),
    node("item", "loop.item"),
    step("X"),
    step("Y"),
    step("J"),
    node("done", "loop.yield"),
    step("after"),
  ];
  const wiring: Wiring[] = [
    ["start", "out", "F"],
    ["F", "body", "item"],
    ["F", "done", "after"],
    ["J", "out", "done"],
  ];
  if (parallel) {
    nodes.splice(3, 0, splitNode("S", "a", "b"));
    wiring.push(
      ["item", "out", "S"],
      ["S", "a", "X"],
      ["S", "b", "Y"],
      ["X", "out", "J"],
      ["Y", "out", "J"],
    );
  } else {
    wiring.push(["item", "out", "X"], ["X", "out", "Y"], ["Y", "out", "J"]);
  }
  return build(nodes, wiring);
}

function switchChain(layers: number): WorkflowGraph {
  const nodes = [start()];
  const wiring: Wiring[] = [];
  let previous = "start";
  for (let layer = 0; layer < layers; layer += 1) {
    nodes.push(switchNode(`S${layer}`, "a", "b"), step(`M${layer}`));
    wiring.push(
      [previous, "out", `S${layer}`],
      [`S${layer}`, "a", `M${layer}`],
      [`S${layer}`, "b", `M${layer}`],
    );
    previous = `M${layer}`;
  }
  return build(nodes, wiring);
}

describe("run conditions", () => {
  it("runs the two legs of a Split together, and both precede the join", () => {
    const a = analyseGraph(split2());
    expect(together(a, "A", "B")).toBe(true);
    expect(wiresTogether(a)).toBe(true);
    expect(["A", "B", "S"].every((id) => precedes(a).has(id))).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "A.out": true, "B.out": true });
  });

  it("never runs the two arms of an If together, and neither precedes their rejoin", () => {
    const a = analyseGraph(ifElse());
    expect(together(a, "A", "B")).toBe(false);
    expect(together(a, "A", "A")).toBe(true);
    expect(wiresTogether(a)).toBe(false);
    expect(precedes(a)).toEqual(new Set(["J", "I", "start"]));
    expect(isAlways(a, "J")).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "A.out": false, "B.out": false });
  });

  it("runs a fan-out together and apart from the other port", () => {
    const a = analyseGraph(mixed());
    expect(together(a, "A", "B")).toBe(true);
    expect(together(a, "A", "C")).toBe(false);
    expect(wiresTogether(a)).toBe(true);
    expect(["A", "B", "C"].some((id) => precedes(a).has(id))).toBe(false);
  });

  it("runs a Split's other leg with each arm of an If", () => {
    const a = analyseGraph(nested());
    expect(together(a, "A", "B")).toBe(false);
    expect(together(a, "A", "C") && together(a, "B", "C")).toBe(true);
    expect(["C", "S", "I"].every((id) => precedes(a).has(id))).toBe(true);
    expect(["A", "B"].some((id) => precedes(a).has(id))).toBe(false);
  });

  it("lets a step reached from both ports precede the join, its sibling arm not", () => {
    const a = analyseGraph(common());
    expect(together(a, "K", "A")).toBe(true);
    expect(precedes(a).has("K")).toBe(true);
    expect(precedes(a).has("A")).toBe(false);
    expect(wiresWhenever(a)).toEqual({ "K.out": true, "A.out": false });
  });

  it("runs a routed leg with its handler but never its two wires together", () => {
    const a = analyseGraph(routedLeg());
    expect(together(a, "A", "H")).toBe(true);
    expect(["A", "B", "S"].every((id) => precedes(a).has(id))).toBe(true);
    expect(precedes(a).has("H")).toBe(false);
    expect(wiresTogether(a)).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "A.out": false, "H.default": false, "B.out": true });
  });

  it("runs a fan-out from one port together", () => {
    const a = analyseGraph(fanoutPartial());
    expect(together(a, "A", "B")).toBe(true);
    expect(precedes(a).has("A") && precedes(a).has("B")).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "A.out": true, "B.true": false });
  });

  it("never runs two ports wired straight into a join together", () => {
    const a = analyseGraph(straight());
    expect(wiresTogether(a)).toBe(false);
    expect(precedes(a)).toEqual(new Set(["J", "S", "start"]));
  });

  it("graph b: a step reached from both ports runs with the arm before it", () => {
    const a = analyseGraph(reachedFromBothPorts());
    expect(together(a, "P", "T")).toBe(true);
    expect(wiresTogether(a)).toBe(true);
    expect(precedes(a).has("T")).toBe(true);
    expect(precedes(a).has("P")).toBe(false);
  });

  it("graph c: a leg skipped by one port does not precede the join", () => {
    const a = analyseGraph(skippedByOnePort());
    expect(together(a, "A", "T")).toBe(true);
    expect(precedes(a).has("T")).toBe(true);
    expect(precedes(a).has("A")).toBe(false);
  });

  it("graph a: two outputs after a step reached from both ports run together", () => {
    expect(together(analyseGraph(outputsAfterBothPorts()), "O1", "O2")).toBe(true);
  });

  it("never runs a nested If's two branches together", () => {
    const a = analyseGraph(nestedWithSharedElse());
    expect(together(a, "A", "T")).toBe(false);
    expect(wiresTogether(a)).toBe(false);
    expect(isAlways(a, "J")).toBe(true);
    expect(precedes(a)).toEqual(new Set(["J", "X", "start"]));
  });

  it("never runs a Switch's shared step with its other way out", () => {
    const a = analyseGraph(switchSharingAStep());
    expect(together(a, "s", "C")).toBe(false);
    expect(wiresTogether(a)).toBe(false);
    expect(isAlways(a, "J")).toBe(true);
  });

  it("lets an unwired way out stop a branch running whenever the join does", () => {
    const a = analyseGraph(unwiredOtherwise());
    expect(wiresTogether(a)).toBe(false);
    expect(wiresWhenever(a)).toEqual({ "A.out": false, "B.out": false });
    expect(isAlways(a, "J")).toBe(false);
  });

  it("folds every way out of a three-port Switch into always", () => {
    const a = analyseGraph(switchFullyMerged());
    expect(isAlways(a, "J")).toBe(true);
    expect(isAlways(a, "A1")).toBe(false);
  });

  it("splits the run in two at a routed error port", () => {
    const a = analyseGraph(routedErrorPort());
    expect(together(a, "A", "H")).toBe(false);
    expect(together(a, "A", "B")).toBe(false);
    expect(wiresTogether(a)).toBe(false);
    expect(isAlways(a, "J")).toBe(true);
    expect(precedes(a)).toEqual(new Set(["J", "R", "start"]));
  });

  it("analyses a loop body against the loop", () => {
    const a = analyseGraph(loopGraph());
    expect(together(a, "X", "Y")).toBe(true);
    expect(precedes(a, "item")).toEqual(new Set(["item", "F"]));
    expect(["X", "Y", "S", "F", "item"].every((id) => precedes(a, "J").has(id))).toBe(true);
    expect(precedes(a, "J").has("start")).toBe(false);
    expect(a.precede.has("after")).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "X.out": true, "Y.out": true });
    expect(together(a, "X", "after") && together(a, "after", "X")).toBe(true);
    expect(together(analyseGraph(loopGraph(false)), "X", "after")).toBe(true);
  });

  it("reads a wire from the loop itself as always live inside its body", () => {
    const a = analyseGraph(loopGraph());
    const wire = (a.incoming.get("item") as JoinWire[])[0] as JoinWire;
    expect(wireCondition(a, "item", wire)?.terms).toEqual([new Set()]);
    expect(wireRunsWhenever(a, "item", wire)).toBe(true);
  });

  it("says a step runs whenever a later one does only if it comes before it", () => {
    const a = analyseGraph(ifElse());
    expect(runsWhenever(a, "I", "J")).toBe(true);
    expect(runsWhenever(a, "J", "I")).toBe(false);
    expect(runsWhenever(a, "A", "J")).toBe(false);
    expect(runsWhenever(a, "A", "A")).toBe(true);
  });

  it("does not say a step in a loop runs whenever a step after the loop does", () => {
    const a = analyseGraph(loopGraph());
    expect(runsWhenever(a, "X", "after")).toBe(false);
    expect(runsWhenever(a, "J", "after")).toBe(false);
    expect(runsWhenever(a, "F", "after")).toBe(true);
    expect(runsWhenever(a, "start", "after")).toBe(true);
    expect(runsWhenever(a, "F", "X")).toBe(true);
    expect(runsWhenever(a, "item", "X")).toBe(true);
  });

  it("says a step before a loop runs whenever a step in it does", () => {
    const a = analyseGraph(loopGraph());
    expect(runsWhenever(a, "F", "X")).toBe(true);
    expect(runsWhenever(a, "start", "X")).toBe(true);
    expect(runsWhenever(a, "X", "start")).toBe(false);
  });
});

describe("the term cap", () => {
  it("makes a condition past the cap unknown, and never accepts it", () => {
    const a = analyseGraph(switchChain(7));
    const terms = (id: string) => (a.conditions.get(id) as { terms: unknown[] }).terms.length;
    expect(a.conditions.get("M4")?.unknown).toBe(false);
    expect(terms("M5")).toBe(2 ** 6);
    expect(2 ** 6).toBe(MAX_TERMS);
    expect(a.conditions.get("M5")?.unknown).toBe(false);
    expect(a.conditions.get("M6")).toEqual({ terms: [], unknown: true });
    expect(canRunTogether(a, "M6", "start")).toBe(true);
    expect(canRunTogether(a, "start", "M6")).toBe(true);
    expect(runsWhenever(a, "start", "M6")).toBe(false);
    expect(runsWhenever(a, "M6", "start")).toBe(false);
    const unknown = a.conditions.get("M6") as NonNullable<ReturnType<typeof a.conditions.get>>;
    const always = a.conditions.get("start") as typeof unknown;
    expect(covers(unknown, always)).toBe(false);
    expect(covers(always, unknown)).toBe(false);
  });

  it("makes a step after an unknown condition unknown too", () => {
    const a = analyseGraph(switchChain(8));
    expect(a.conditions.get("S7")?.unknown).toBe(true);
    expect(a.conditions.get("M7")?.unknown).toBe(true);
  });
});

/** A 64-term step feeding `ifs` Ifs whose `true` ways all lead to one step. */
function fanInGraph(ifs: number): WorkflowGraph {
  const chain = switchChain(6);
  const edges = chain.edges.map(
    (e) => [e.source_node_id, e.source_port, e.target_node_id] as Wiring,
  );
  const nodes = [...chain.nodes, step("T")];
  for (let index = 0; index < ifs; index += 1) {
    nodes.push(ifNode(`I${index}`));
    edges.push(["M5", "out", `I${index}`], [`I${index}`, "true", "T"]);
  }
  return build(nodes, edges);
}

/** A 64-term step followed by `steps` steps in a row (Ifs wired by `true` when `branching`). */
function longChainGraph(steps: number, branching: boolean): WorkflowGraph {
  const chain = switchChain(6);
  const edges = chain.edges.map(
    (e) => [e.source_node_id, e.source_port, e.target_node_id] as Wiring,
  );
  const nodes = [...chain.nodes];
  let previous = "M5";
  for (let index = 0; index < steps; index += 1) {
    nodes.push(branching ? ifNode(`C${index}`) : step(`C${index}`));
    edges.push([previous, branching && index > 0 ? "true" : "out", `C${index}`]);
    previous = `C${index}`;
  }
  return build(nodes, edges);
}

describe("work bounds", () => {
  it("analyses a fan-in of many wide conditions in bounded time and refuses it safely", () => {
    const g = fanInGraph(450);
    expect(g.nodes.length).toBeLessThanOrEqual(500);
    expect(g.edges.length).toBeLessThanOrEqual(2000);
    const started = performance.now();
    const a = analyseGraph(g);
    expect(performance.now() - started).toBeLessThan(5000);
    expect(a.conditions.get("T")?.unknown).toBe(true);
    expect(canRunTogether(a, "T", "I0")).toBe(true);
    expect(runsWhenever(a, "M5", "T")).toBe(false);
    const wire = (a.incoming.get("T") as JoinWire[])[0] as JoinWire;
    expect(wireRunsWhenever(a, "T", wire)).toBe(false);
  });

  it("analyses a long chain after a wide condition in bounded time, exactly", () => {
    const g = longChainGraph(450, false);
    expect(g.nodes.length).toBeLessThanOrEqual(500);
    const started = performance.now();
    const a = analyseGraph(g);
    expect(performance.now() - started).toBeLessThan(5000);
    expect(precedes(a, "C449").has("M5")).toBe(true);
    expect(runsWhenever(a, "C0", "C449")).toBe(true);
  });

  it("analyses a long chain of choices after a wide condition in bounded time", () => {
    const started = performance.now();
    const a = analyseGraph(longChainGraph(450, true));
    expect(performance.now() - started).toBeLessThan(5000);
    expect(a.conditions.has("C449")).toBe(true);
  });

  it("makes conditions unknown once the build budget is spent", () => {
    const g = switchChain(4);
    const definitions = resolveDefinitions(g, CATALOG);
    const nodeScope = nodeScopeMap(deriveScopes(g, definitions));
    const a = analyse(g, definitions, nodeScope, true, { build: 10 });
    expect(a.conditions.get("M3")?.unknown).toBe(true);
    expect(canRunTogether(a, "M3", "start")).toBe(true);
    expect(runsWhenever(a, "start", "M3")).toBe(false);
  });

  it("falls back once the question budget is spent", () => {
    const g = ifElse();
    const definitions = resolveDefinitions(g, CATALOG);
    const nodeScope = nodeScopeMap(deriveScopes(g, definitions));
    const a = analyse(g, definitions, nodeScope, true, { questions: 0 });
    expect(canRunTogether(a, "A", "B")).toBe(true);
    expect(wiresTogether(a)).toBe(true);
    expect(wiresWhenever(a)).toEqual({ "A.out": false, "B.out": false });
  });

  it("compares two conditions exactly without a budget", () => {
    const a = analyseGraph(ifElse());
    const left = a.conditions.get("A") as NonNullable<ReturnType<typeof a.conditions.get>>;
    const right = a.conditions.get("B") as typeof left;
    const always = a.conditions.get("start") as typeof left;
    expect(covers(left, right) || covers(right, left)).toBe(false);
    expect(covers(left, left) && covers(always, left) && !covers(left, always)).toBe(true);
    expect(mayHoldTogether(left, right)).toBe(false);
    expect(mayHoldTogether(left, always)).toBe(true);
  });

  it("answers the same comparison from memory the second time", () => {
    const a = analyseGraph(ifElse());
    const wire = (a.incoming.get("J") as JoinWire[])[0] as JoinWire;
    expect(wireRunsWhenever(a, "J", wire)).toBe(false);
    expect(wireRunsWhenever(a, "J", wire)).toBe(false);
    expect(runsWhenever(a, "I", "J")).toBe(true);
    expect(runsWhenever(a, "I", "J")).toBe(true);
  });

  it("leaves the other choices of a term alone when folding", () => {
    const g = build(
      [
        start(),
        ifNode("I"),
        switchNode("S", "r1", "r2"),
        step("A1"),
        step("A2"),
        step("A3"),
        step("J"),
      ],
      [
        ["start", "out", "I"],
        ["I", "true", "S"],
        ["S", "r1", "A1"],
        ["S", "r2", "A2"],
        ["S", "otherwise", "A3"],
        ["A1", "out", "J"],
        ["A2", "out", "J"],
        ["A3", "out", "J"],
      ],
    );
    const terms = (analyseGraph(g).conditions.get("J") as { terms: Set<string>[] }).terms;
    expect(terms.map((term) => [...term].map((entry) => entry.replace("\u0000", ".")))).toEqual([
      ["I.true"],
    ]);
  });
});

describe("graphs the analysis must survive", () => {
  it("analyses an unknown step without raising", () => {
    const g = build(
      [
        start(),
        splitNode("S", "a", "b"),
        { ...node("U", "no.such.step"), policy: { on_error: "route" as const } },
        step("B"),
        step("J"),
      ],
      [
        ["start", "out", "S"],
        ["S", "a", "U"],
        ["S", "b", "B"],
        ["U", "out", "J"],
        ["B", "out", "J"],
      ],
    );
    const a = analyseGraph(g);
    expect(together(a, "U", "B")).toBe(true);
    expect(wiresTogether(a)).toBe(true);
    expect(wiresWhenever(a)["U.out"]).toBe(false);
  });

  it("keeps a merge rule closed for a step whose ports it cannot know", () => {
    const g = build(
      [
        start(),
        { ...node("U", "no.such.step"), policy: { on_error: "route" as const } },
        step("A"),
        step("B"),
        step("J"),
      ],
      [
        ["start", "out", "U"],
        ["U", "out", "A"],
        ["U", "error", "B"],
        ["A", "out", "J"],
        ["B", "out", "J"],
      ],
    );
    expect(isAlways(analyseGraph(g), "J")).toBe(false);
  });

  it("has no conditions when the outer graph is cyclic", () => {
    const g = build(
      [start(), step("A"), step("B")],
      [
        ["start", "out", "A"],
        ["A", "out", "B"],
        ["B", "out", "A"],
      ],
    );
    const a = analyseGraph(g);
    expect(a.conditions.size).toBe(0);
    expect(a.precede.size).toBe(0);
    expect(together(a, "A", "B")).toBe(false);
  });

  it("gives a step nothing leads to no condition, and has it run with nothing", () => {
    const g = build(
      [start(), ifNode("I"), step("A"), step("Z"), step("J")],
      [
        ["start", "out", "I"],
        ["I", "true", "A"],
        ["A", "out", "J"],
        ["Z", "out", "J"],
      ],
    );
    const a = analyseGraph(g);
    expect(a.conditions.has("Z") || a.precede.has("Z")).toBe(false);
    expect(together(a, "A", "Z") || together(a, "Z", "A")).toBe(false);
    expect(runsWhenever(a, "Z", "J") || runsWhenever(a, "A", "Z")).toBe(false);
    const wire = (a.incoming.get("J") ?? []).find((w) => w.sourceNodeId === "Z");
    expect(wire && wireCondition(a, "J", wire)).toBeUndefined();
    expect(wire && wireRunsWhenever(a, "J", wire)).toBe(false);
    expect(wiresTogether(a)).toBe(false);
  });

  it("reads two edges from one port as one wire", () => {
    const g = build(
      [start(), step("A"), step("J")],
      [
        ["start", "out", "A"],
        ["A", "out", "J"],
        ["A", "out", "J"],
      ],
    );
    expect(analyseGraph(g).incoming.get("J")).toHaveLength(1);
  });

  it("ignores an edge from a step that is not in the graph", () => {
    const g = split2();
    const ghost = edge("ghost", "nobody", "out", "J", "in");
    expect(analyseGraph({ ...g, edges: [...g.edges, ghost] }).incoming.get("J")).toHaveLength(2);
  });

  it("does not take an edge crossing into a loop body as a way in", () => {
    const g = loopGraph(false);
    const crossing = edge("crossing", "start", "out", "Y", "in");
    const a = analyseGraph({ ...g, edges: [...g.edges, crossing] });
    expect(a.conditions.has("Y")).toBe(true);
  });
});
