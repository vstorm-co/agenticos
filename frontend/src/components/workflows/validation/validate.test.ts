/**
 * Rule-by-rule tests and the fixture-parity ("drift") suite.
 *
 * ## How the drift fixtures are built
 *
 * Each fixture is translated from a case in
 * `backend/tests/test_workflow_graph_validation.py` /
 * `..._internals.py` — the backend validator's own tests. The graph shape (nodes,
 * edges, bindings) matches the Python fixture, and the expected `code` multiset is
 * what `validate_graph` produces on it. Where a backend test isolates one rule with
 * `_action_definition(port_schema=None)` — a control-only input port that no edge
 * can be type-incompatible with — the fixture here does the same, so the mirror is
 * asserted against a clean, single-rule expectation rather than incidental noise.
 *
 * This is **fixture-parity, not a live cross-language check**: the assertions
 * encode the backend's output as it stands today, they do not run the Python
 * validator. If the backend rules change, regenerate a fixture by reading the
 * matching Python test and re-deriving its expected codes here — the code names map
 * one-to-one to the rules in `validate.py`, listed in `./types.ts`.
 *
 * The pass-0 resource checks the client cannot mirror — the size ceiling, granted
 * scopes, `config` against its schema, `TableIORef` liveness, a `LiteralValue`'s
 * type, and a binding's target-field existence — are deliberately absent, and their
 * backend tests have no fixture here.
 */

import { describe, expect, it } from "vitest";

import {
  DEBUG_ECHO,
  LETTER,
  NUMBER,
  OPTIONAL_INPUT,
  PLAIN_OUTPUT,
  REQUIRED_INPUT,
  echo,
  edge,
  graph,
  literalBinding,
  makeCatalog,
  makeDefinition,
  node,
  nodeOutputBinding,
  port,
  testTranslator,
} from "./fixtures";
import {
  availableSourceNodes,
  computeDominators,
  deriveScopes,
  fieldType,
  portShapesCompatible,
  resolveDefinitions,
  resolveFieldType,
  schemaTypeToken,
  typesCompatible,
  UNKNOWN,
  validateGraph,
  MESSAGE_KEYS,
  type ValidationProblem,
} from "./index";
import { nearestCommonDominator } from "./rules";

// Definitions the backend tests register synthetically, translated to catalog
// entries. A `null` "in" port is the backend's `_action_definition(port_schema=None)`
// — it isolates a topology rule from type-compatibility.
const CONSUMER = makeDefinition({
  id: "test.consumer",
  input_schema: REQUIRED_INPUT,
  output_schema: PLAIN_OUTPUT,
  ports: [port("in", "input", null), port("out", "output", PLAIN_OUTPUT)],
});
const CONSUMER_NOREQ = makeDefinition({
  id: "test.consumer_noreq",
  output_schema: PLAIN_OUTPUT,
  ports: [port("in", "input", null), port("out", "output", PLAIN_OUTPUT)],
});
const OPTIONAL_CONSUMER = makeDefinition({
  id: "test.optional_consumer",
  input_schema: OPTIONAL_INPUT,
  output_schema: PLAIN_OUTPUT,
  ports: [port("in", "input", null), port("out", "output", PLAIN_OUTPUT)],
});
const OTHER_SHAPE = makeDefinition({
  id: "test.other_shape",
  output_schema: PLAIN_OUTPUT,
  ports: [port("in", "input", REQUIRED_INPUT), port("out", "output", PLAIN_OUTPUT)],
});
const WANTS_NUMBER = makeDefinition({
  id: "test.wants_a_number",
  input_schema: NUMBER,
  ports: [port("in", "input", null)],
});
const LETTER_SOURCE = makeDefinition({
  id: "test.letter_source",
  output_schema: LETTER,
  ports: [port("out", "output", LETTER)],
});
const LETTER_SINK = makeDefinition({
  id: "test.letter_sink",
  ports: [port("in", "input", LETTER), port("out", "output", LETTER)],
});
const IF = makeDefinition({
  id: "logic.if",
  kind: "control",
  ports: [
    port("in", "input", null),
    port("then", "output", null),
    port("otherwise", "output", null),
  ],
});
const MERGE = makeDefinition({
  id: "logic.merge",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const SWITCH = makeDefinition({
  id: "logic.switch",
  kind: "control",
  ports: [port("in", "input", null), port("a", "output", null), port("b", "output", null)],
});
const TWO_PORTS = makeDefinition({
  id: "test.two_output_ports",
  ports: [port("in", "input", null), port("out_a", "output", null), port("out_b", "output", null)],
});
const FOREACH = makeDefinition({
  id: "control.foreach",
  kind: "control",
  ports: [port("in", "input", null), port("body", "output", null), port("done", "output", null)],
});

const CATALOG = makeCatalog([
  DEBUG_ECHO,
  CONSUMER,
  CONSUMER_NOREQ,
  OPTIONAL_CONSUMER,
  OTHER_SHAPE,
  WANTS_NUMBER,
  LETTER_SOURCE,
  LETTER_SINK,
  IF,
  MERGE,
  SWITCH,
  TWO_PORTS,
  FOREACH,
]);

function codesOf(problems: ValidationProblem[]): string[] {
  return problems.map((problem) => problem.code).sort();
}

function run(g: Parameters<typeof validateGraph>[0]): ValidationProblem[] {
  return validateGraph(g, CATALOG, testTranslator);
}

describe("drift parity — happy graphs the backend publishes", () => {
  it("a single node graph with no bindings", () => {
    expect(run(graph({ entry: "a", nodes: [echo("a")] }))).toEqual([]);
  });

  it("a binding to a node on every path", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [nodeOutputBinding("b", "value", "a", "out", ["echoed"])],
    });
    expect(run(g)).toEqual([]);
  });

  it("an edge between two ports of the identical shape", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "test.letter_source"), node("b", "test.letter_sink")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect(run(g)).toEqual([]);
  });

  it("a merge from one logic.if", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("branch", "logic.if"),
        echo("then"),
        echo("else"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "branch", "in"),
        edge("e2", "branch", "then", "then", "in"),
        edge("e3", "branch", "otherwise", "else", "in"),
        edge("e4", "then", "out", "m", "in"),
        edge("e5", "else", "out", "m", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("a control node fanning out two branches", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("branch", "logic.if"), echo("then"), echo("else")],
      edges: [
        edge("e1", "entry", "out", "branch", "in"),
        edge("e2", "branch", "then", "then", "in"),
        edge("e3", "branch", "otherwise", "else", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("a required input bound exactly once", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [literalBinding("b", "value", "one")],
    });
    expect(run(g)).toEqual([]);
  });
});

describe("drift parity — graphs the backend refuses", () => {
  it("rule 1 — an entry node not in the graph", () => {
    expect(codesOf(run(graph({ entry: "ghost", nodes: [echo("a")] })))).toEqual([
      "entry-not-in-graph",
    ]);
  });

  it("rule 1 — an entry node that is the target of an edge", () => {
    const g = graph({
      entry: "b",
      nodes: [echo("a"), node("b", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["entry-is-edge-target", "unreachable-node"]);
  });

  it("rule 2 — a second unreachable source node", () => {
    const g = graph({ entry: "entry", nodes: [echo("entry"), echo("island")] });
    expect(codesOf(run(g))).toEqual(["unreachable-node"]);
  });

  it("rule 3 — an edge between incompatible port shapes", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.other_shape")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["edge-incompatible"]);
  });

  it("rule 3 — an edge naming a source port the definition does not declare", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq")],
      edges: [edge("e1", "a", "nope", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["edge-source-port-unknown"]);
  });

  it("rule 3 — an edge naming a target port the definition does not declare", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "nope")],
    });
    expect(codesOf(run(g))).toEqual(["edge-target-port-unknown"]);
  });

  it("rule 3 — a binding field path that does not exist", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [nodeOutputBinding("b", "value", "a", "out", ["no_such_field"])],
    });
    expect(codesOf(run(g))).toEqual(["binding-field-path-unknown"]);
  });

  it("rule 3 — a field path stepping into a scalar field", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [nodeOutputBinding("b", "value", "a", "out", ["echoed", "x"])],
    });
    expect(codesOf(run(g))).toEqual(["binding-field-path-unknown"]);
  });

  it("rule 3 — a binding field path resolving to an incompatible field", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.wants_a_number")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [nodeOutputBinding("b", "letter", "a", "out", ["echoed"])],
    });
    expect(codesOf(run(g))).toEqual(["binding-incompatible"]);
  });

  it("rule 4 — a binding to a node not on every path", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("branch", "logic.if"),
        node("b", "test.consumer_noreq"),
        node("c", "test.consumer"),
      ],
      edges: [
        edge("e1", "entry", "out", "branch", "in"),
        edge("e2", "branch", "then", "b", "in"),
        edge("e3", "branch", "then", "c", "in"),
        edge("e4", "b", "out", "c", "in"),
      ],
      bindings: [nodeOutputBinding("c", "value", "b", "out", ["value"])],
    });
    expect(codesOf(run(g))).toEqual(["binding-unavailable"]);
  });

  it("rule 4 — a binding to the node's own output", () => {
    const g = graph({
      entry: "c",
      nodes: [node("c", "test.consumer")],
      bindings: [nodeOutputBinding("c", "value", "c", "out", ["value"])],
    });
    expect(codesOf(run(g))).toEqual(["binding-self-reference"]);
  });

  it("rule 4 — a binding into a node the cycle left unordered is left to rule 7", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer_noreq")],
      edges: [
        edge("e1", "a", "out", "b", "in"),
        edge("e2", "b", "out", "c", "in"),
        edge("e3", "c", "out", "b", "in"),
      ],
      bindings: [nodeOutputBinding("c", "value", "b", "out", [])],
    });
    // The binding's node is in the cycle, so rule 4 stays silent; rule 7 refuses.
    expect(codesOf(run(g))).toEqual(["node-in-cycle", "node-in-cycle"]);
  });

  it("rule 5 — a lone merge with fewer than two predecessors is left alone", () => {
    expect(run(graph({ entry: "m", nodes: [node("m", "logic.merge")] }))).toEqual([]);
  });

  it("rule 5 — a merge whose branches share no common dominator", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), echo("b"), node("c", "logic.merge")],
      edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "b", "out", "c", "in")],
    });
    expect(codesOf(run(g))).toEqual(["merge-no-common-dominator", "unreachable-node"]);
  });

  it("rule 5 — a merge whose common dominator is not logic.if", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("s", "logic.switch"),
        echo("ba"),
        echo("bb"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "s", "in"),
        edge("e2", "s", "a", "ba", "in"),
        edge("e3", "s", "b", "bb", "in"),
        edge("e4", "ba", "out", "m", "in"),
        edge("e5", "bb", "out", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-not-from-if"]);
  });

  it("rule 5 — a merge whose branches leave the if through the same port", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("branch", "logic.if"),
        echo("t"),
        echo("o"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "branch", "in"),
        edge("e2", "branch", "then", "t", "in"),
        edge("e3", "branch", "then", "o", "in"),
        edge("e4", "t", "out", "m", "in"),
        edge("e5", "o", "out", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-not-exclusive"]);
  });

  it("rule 5 — a merge with two edges from the same branch", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("c", "logic.merge")],
      edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "a", "out", "c", "in")],
    });
    expect(codesOf(run(g))).toEqual(["fanout-port-multiple-edges", "merge-duplicate-branch"]);
  });

  it("rule 5 — a merge branch reconverged from both if arms", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("branch", "logic.if"),
        echo("t"),
        echo("e"),
        node("a", "test.consumer_noreq"),
        echo("b"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("x1", "entry", "out", "branch", "in"),
        edge("x2", "branch", "then", "t", "in"),
        edge("x3", "branch", "then", "b", "in"),
        edge("x4", "branch", "otherwise", "e", "in"),
        edge("x5", "t", "out", "a", "in"),
        edge("x6", "e", "out", "a", "in"),
        edge("x7", "a", "out", "m", "in"),
        edge("x8", "b", "out", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-not-exclusive"]);
  });

  it("rule 6 — an edge reaching into a scope body from outside it", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("loop", "control.foreach"),
        node("body", "test.consumer_noreq"),
        echo("intruder"),
      ],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "body", "in"),
        edge("e3", "loop", "done", "intruder", "in"),
        edge("e4", "intruder", "out", "body", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["edge-crosses-scope"]);
  });

  it("rule 6 — the two declared boundary edges publish", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("loop", "control.foreach"),
        node("body", "test.consumer_noreq"),
        echo("after"),
      ],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "body", "in"),
        edge("e3", "loop", "done", "after", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("rule 6 — a binding crossing out of a scope body", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("loop", "control.foreach"),
        node("body", "test.consumer_noreq"),
        node("after", "test.consumer"),
      ],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "body", "in"),
        edge("e3", "loop", "done", "after", "in"),
      ],
      bindings: [nodeOutputBinding("after", "value", "body", "out", ["value"])],
    });
    // The binding both crosses the boundary and reads a node not on every path.
    expect(codesOf(run(g))).toEqual(["binding-crosses-scope", "binding-unavailable"]);
  });

  it("rule 7 — a node inside a cycle", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("a", "test.consumer_noreq"), node("b", "test.consumer_noreq")],
      edges: [
        edge("e1", "entry", "out", "a", "in"),
        edge("e2", "a", "out", "b", "in"),
        edge("e3", "b", "out", "a", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["node-in-cycle", "node-in-cycle"]);
  });

  it("rule 7 — a cycle inside a scope body", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("loop", "control.foreach"),
        node("x", "test.consumer_noreq"),
        node("y", "test.consumer_noreq"),
      ],
      edges: [
        edge("e1", "entry", "out", "loop", "in"),
        edge("e2", "loop", "body", "x", "in"),
        edge("e3", "x", "out", "y", "in"),
        edge("e4", "y", "out", "x", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["node-in-scope-cycle", "node-in-scope-cycle"]);
  });

  it("rule 8 — a non-control node sending through two ports", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("a", "test.two_output_ports"),
        node("b", "test.consumer_noreq"),
        node("c", "test.consumer_noreq"),
      ],
      edges: [
        edge("e1", "entry", "out", "a", "in"),
        edge("e2", "a", "out_a", "b", "in"),
        edge("e3", "a", "out_b", "c", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["fanout-multiple-ports"]);
  });

  it("rule 8 — a non-control node with two edges on one port", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "a", "out", "c", "in")],
    });
    expect(codesOf(run(g))).toEqual(["fanout-port-multiple-edges"]);
  });

  it("rule 9 — an unbound required input", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["input-not-bound"]);
  });

  it("rule 9 — a required input bound twice", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [literalBinding("b", "value", "one"), literalBinding("b", "value", "two")],
    });
    expect(codesOf(run(g))).toEqual(["input-bound-twice"]);
  });

  it("rule 9 — an optional input bound twice", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.optional_consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [literalBinding("b", "value", "one"), literalBinding("b", "value", "two")],
    });
    expect(codesOf(run(g))).toEqual(["input-bound-twice"]);
  });

  it("resource resolution — an edge and a binding touching an unresolvable definition skip rule 3", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "no.such.node"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
      bindings: [nodeOutputBinding("b", "value", "a", "out", [])],
    });
    // Only the unresolvable node is named; rule 3 has no schema to compare and stays quiet.
    expect(codesOf(run(g))).toEqual(["unknown-definition"]);
  });

  it("resource resolution — an unknown definition version", () => {
    const g = graph({ entry: "a", nodes: [node("a", "debug.echo", { message: "hi" }, 99)] });
    expect(codesOf(run(g))).toEqual(["unknown-definition"]);
  });

  it("collects every violated rule in one refusal", () => {
    const g = graph({ entry: "ghost", nodes: [node("a", "debug.echo", { message: "hi" }, 99)] });
    expect(codesOf(run(g))).toEqual(["entry-not-in-graph", "unknown-definition"]);
  });
});

describe("dangling references are refused on their own, ahead of every rule", () => {
  it("an edge whose source node is not in the graph", () => {
    const g = graph({
      entry: "b",
      nodes: [echo("b")],
      edges: [edge("e1", "ghost", "out", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["edge-source-node-missing"]);
  });

  it("an edge whose target node is not in the graph", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a")],
      edges: [edge("e1", "a", "out", "ghost", "in")],
    });
    expect(codesOf(run(g))).toEqual(["edge-target-node-missing"]);
  });

  it("a binding targeting a node not in the graph", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a")],
      bindings: [literalBinding("ghost", "value", 1)],
    });
    expect(codesOf(run(g))).toEqual(["binding-target-node-missing"]);
  });

  it("a binding reading from a node not in the graph", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      bindings: [nodeOutputBinding("b", "value", "ghost", "out", [])],
    });
    expect(codesOf(run(g))).toEqual(["binding-source-node-missing"]);
  });
});

describe("validateGraph message rendering", () => {
  it("translates each code through its key and passes params", () => {
    const g = graph({ entry: "a", nodes: [node("a", "debug.echo", { message: "hi" }, 99)] });
    const [problem] = run(g);
    expect(problem?.code).toBe("unknown-definition");
    expect(problem?.message).toContain(MESSAGE_KEYS["unknown-definition"]);
    expect(problem?.message).toContain("debug.echo");
    expect(problem?.nodeId).toBe("a");
  });

  it("carries the port param on a fan-out problem", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "a", "out", "c", "in")],
    });
    const problem = run(g).find((p) => p.code === "fanout-port-multiple-edges");
    expect(problem?.message).toContain("out");
    expect(problem?.nodeId).toBe("a");
  });

  it("scopes an edge problem to the edge and a graph rule to neither node nor edge", () => {
    const edgeProblem = run(
      graph({
        entry: "a",
        nodes: [echo("a"), node("b", "test.other_shape")],
        edges: [edge("edge-x", "a", "out", "b", "in")],
      }),
    ).find((p) => p.code === "edge-incompatible");
    expect(edgeProblem?.edgeId).toBe("edge-x");
    expect(edgeProblem?.nodeId).toBeNull();

    const [graphProblem] = run(graph({ entry: "ghost", nodes: [echo("a")] }));
    expect(graphProblem?.nodeId).toBeNull();
    expect(graphProblem?.edgeId).toBeNull();
    expect(graphProblem?.field).toBeNull();
  });
});

describe("nearestCommonDominator — the safety cases a real dominator tree never produces", () => {
  it("returns null when the branches' dominator sets do not intersect", () => {
    const dominators = new Map([
      ["x", new Set(["x"])],
      ["y", new Set(["y"])],
    ]);
    expect(nearestCommonDominator(["x", "y"], dominators)).toBeNull();
  });

  it("returns null when no member of the intersection dominates every other", () => {
    // A hand-built, deliberately non-tree map: the intersection {p, q} is
    // non-empty, but neither p nor q is itself in the map, so none dominates all.
    const dominators = new Map([
      ["x", new Set(["p", "q", "x"])],
      ["y", new Set(["p", "q", "y"])],
    ]);
    expect(nearestCommonDominator(["x", "y"], dominators)).toBeNull();
  });

  it("returns null when a branch has no dominator set at all", () => {
    const dominators = new Map([["x", new Set(["x"])]]);
    expect(nearestCommonDominator(["x", "missing"], dominators)).toBeNull();
  });
});

describe("binding-picker helpers", () => {
  const linear = graph({
    entry: "a",
    nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer")],
    edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "c", "in")],
  });

  it("computeDominators reports the nodes on every path to a node", () => {
    const dominators = computeDominators(linear, CATALOG);
    expect(dominators.get("c")).toEqual(new Set(["a", "b", "c"]));
  });

  it("availableSourceNodes is the dominators minus the node itself", () => {
    expect(availableSourceNodes(linear, CATALOG, "c")).toEqual(new Set(["a", "b"]));
  });

  it("availableSourceNodes is empty when the node has no dominator verdict", () => {
    const cyclic = graph({
      entry: "a",
      nodes: [node("a", "test.consumer_noreq"), node("b", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "a", "in")],
    });
    expect(availableSourceNodes(cyclic, CATALOG, "a")).toEqual(new Set());
  });

  it("re-exports the schema helpers the picker composes", () => {
    expect(portShapesCompatible(null, null)).toBe(true);
    expect(
      typesCompatible(
        fieldType(DEBUG_ECHO, "message"),
        resolveFieldType(DEBUG_ECHO, "out", ["echoed"]),
      ),
    ).toBe(true);
    expect(schemaTypeToken(UNKNOWN)).toBe("unknown");
    expect(deriveScopes(linear, resolveDefinitions(linear, CATALOG))).toEqual([]);
  });
});
