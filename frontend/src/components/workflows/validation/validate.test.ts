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
  computePrecede,
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
import { branchKeys } from "./rules";

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
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    port("then", "output", null),
    port("otherwise", "output", null),
  ],
});
const YES_NO = makeDefinition({
  id: "decide.yes_no",
  kind: "control",
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    port("yes", "output", null),
    port("no", "output", null),
    port("unsure", "output", null),
  ],
});
const CLASSIFY = makeDefinition({
  id: "ai.classify",
  kind: "control",
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    port("needs_reply", "output", null),
    port("other", "output", null),
    port("unsure", "output", null),
  ],
});
const LOGIC_SWITCH = makeDefinition({
  id: "logic.switch",
  kind: "control",
  exclusive_branches: true,
  ports: [port("in", "input", null), port("otherwise", "output", null)],
});
const ERROR_HANDLE = makeDefinition({
  id: "error.handle",
  kind: "control",
  exclusive_branches: true,
  ports: [port("in", "input", null), port("default", "output", null)],
});
const HUMAN_APPROVAL = makeDefinition({
  id: "human.approval",
  kind: "control",
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    port("approved", "output", null),
    port("rejected", "output", null),
  ],
});
const MERGE = makeDefinition({
  id: "logic.merge",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const SPLIT = makeDefinition({
  id: "logic.split",
  kind: "control",
  ports: [port("in", "input", null)],
});
const CORE_OUTPUT = makeDefinition({
  id: "core.output",
  ports: [port("in", "input", null)],
});
const WEBHOOK_RESPOND = makeDefinition({
  id: "webhook.respond",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const SWITCH = makeDefinition({
  id: "test.fanout",
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

const WEBHOOK = makeDefinition({
  id: "trigger.webhook",
  category: "triggers",
  ports: [port("out", "output", PLAIN_OUTPUT)],
  output_schema: PLAIN_OUTPUT,
});
const SCHEDULE = makeDefinition({
  id: "trigger.schedule",
  category: "triggers",
  ports: [port("out", "output", PLAIN_OUTPUT)],
  output_schema: PLAIN_OUTPUT,
});

const PICKS_AGENT = makeDefinition({
  id: "test.picks_agent",
  config_schema: {
    type: "object",
    properties: { agent: { type: "string" }, note: { type: "string" } },
    required: ["agent"],
  },
  input_schema: null,
  ports: [port("in", "input", null), port("out", "output", PLAIN_OUTPUT)],
});

const CATALOG = makeCatalog([
  PICKS_AGENT,
  WEBHOOK,
  SCHEDULE,
  YES_NO,
  CLASSIFY,
  LOGIC_SWITCH,
  ERROR_HANDLE,
  HUMAN_APPROVAL,
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
  SPLIT,
  CORE_OUTPUT,
  WEBHOOK_RESPOND,
  SWITCH,
  TWO_PORTS,
  FOREACH,
]);

function codesOf(problems: ValidationProblem[]): string[] {
  return problems.map((problem) => problem.code).sort();
}

/** The codes about how steps join - what these tests are about, beside the catalog's own noise. */
function joinCodes(problems: ValidationProblem[]): string[] {
  return codesOf(problems).filter((code) => code.startsWith("merge-") || code.endsWith("-shared"));
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
      bindings: [literalBinding("branch", "value", true)],
    });
    expect(run(g)).toEqual([]);
  });

  it("a merge from a decision step, which takes one answer per run", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("ask", "decide.yes_no"),
        echo("yes"),
        echo("no"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "ask", "in"),
        edge("e2", "ask", "yes", "yes", "in"),
        edge("e3", "ask", "no", "no", "in"),
        edge("e4", "yes", "out", "m", "in"),
        edge("e5", "no", "out", "m", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("a merge from a classify step's category and its unsure port", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("sort", "ai.classify"),
        echo("reply"),
        echo("unsure"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "sort", "in"),
        edge("e2", "sort", "needs_reply", "reply", "in"),
        edge("e3", "sort", "unsure", "unsure", "in"),
        edge("e4", "reply", "out", "m", "in"),
        edge("e5", "unsure", "out", "m", "in"),
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
      bindings: [literalBinding("branch", "value", true)],
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

  it("rule 1 — a trigger that is not where the graph starts", () => {
    const g = graph({
      entry: "w",
      nodes: [node("w", "trigger.webhook"), node("s", "trigger.schedule")],
    });
    expect(run(g)).toEqual(
      expect.arrayContaining([expect.objectContaining({ nodeId: "s", code: "trigger-not-entry" })]),
    );
    expect(codesOf(run(graph({ entry: "w", nodes: [node("w", "trigger.webhook")] })))).toEqual([]);
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
        edge("e3", "branch", "otherwise", "c", "in"),
      ],
      bindings: [
        literalBinding("branch", "value", true),
        nodeOutputBinding("c", "value", "b", "out", ["value"]),
      ],
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

  it("rule 5 — a merge whose branches share no common dominator is not told to change mode", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), echo("b"), node("c", "logic.merge")],
      edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "b", "out", "c", "in")],
    });
    expect(codesOf(run(g))).toEqual(["unreachable-node"]);
  });

  it("rule 5 — a merge whose common dominator is not logic.if", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        // Any step that is not one of the exclusive branching steps.
        node("s", "test.fanout"),
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
    expect(codesOf(run(g))).toEqual(["merge-wait-for-all"]);
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
      bindings: [literalBinding("branch", "value", true)],
    });
    expect(codesOf(run(g))).toEqual(["merge-wait-for-all"]);
  });

  it("rule 5 — a merge with two edges from the same branch", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("c", "logic.merge")],
      edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "a", "out", "c", "in")],
    });
    expect(codesOf(run(g))).toEqual(["merge-duplicate-branch"]);
  });

  it("rule 5 — a merge may take two ports of one branching step straight", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("c", "ai.classify"), node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "c", "in"),
        edge("e2", "c", "needs_reply", "m", "in"),
        edge("e3", "c", "unsure", "m", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("rule 5 — a merge may take a port straight and another through a leg", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("c", "ai.classify"), echo("leg"), node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "c", "in"),
        edge("e2", "c", "needs_reply", "m", "in"),
        edge("e3", "c", "other", "leg", "in"),
        edge("e4", "leg", "out", "m", "in"),
      ],
    });
    expect(run(g)).toEqual([]);
  });

  it("rule 5 — a merge taking a port straight and through a leg of the same port", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("c", "ai.classify"), echo("leg"), node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "c", "in"),
        edge("e2", "c", "other", "m", "in"),
        edge("e3", "c", "other", "leg", "in"),
        edge("e4", "leg", "out", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-wait-for-all"]);
  });

  it("rule 5 — a merge taking the same port of one step twice stays refused", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("c", "ai.classify"), node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "c", "in"),
        edge("e2", "c", "other", "m", "in"),
        edge("e3", "c", "other", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-duplicate-branch"]);
  });

  it("rule 5 — a merge may join the branches of a step that routes its errors", () => {
    const routed = { ...node("s", "test.consumer_noreq"), policy: { on_error: "route" as const } };
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        routed,
        node("ok", "test.consumer_noreq"),
        node("bad", "test.consumer_noreq"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "s", "in"),
        edge("e2", "s", "out", "ok", "in"),
        edge("e3", "s", "error", "bad", "in"),
        edge("e4", "ok", "out", "m", "in"),
        edge("e5", "bad", "out", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual([]);
  });

  it("rule 5 — a merge may take a routed step's out and error ports straight", () => {
    const routed = { ...node("s", "test.consumer_noreq"), policy: { on_error: "route" as const } };
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), routed, node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "s", "in"),
        edge("e2", "s", "out", "m", "in"),
        edge("e3", "s", "error", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual([]);
  });

  it("rule 5 — a merge taking two ports of a step that does not branch exclusively", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), node("f", "test.fanout"), node("m", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "f", "in"),
        edge("e2", "f", "a", "m", "in"),
        edge("e3", "f", "b", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-wait-for-all"]);
  });

  it("rule 5 — a merge fed through two ports of a non-exclusive step below an exclusive one", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("c", "ai.classify"),
        node("x", "test.fanout"),
        node("m", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "c", "in"),
        edge("e2", "c", "needs_reply", "m", "in"),
        edge("e3", "c", "other", "x", "in"),
        edge("e4", "x", "a", "m", "in"),
        edge("e5", "x", "b", "m", "in"),
      ],
    });
    expect(codesOf(run(g))).toEqual(["merge-together-uncertain"]);
  });

  describe("an output an author names may not reuse a port the step has", () => {
    const cases: [string, string, Record<string, unknown>, string][] = [
      [
        "logic.switch",
        "otherwise",
        { rules: [{ name: "a" }, { name: "otherwise" }] },
        "rules/1/name",
      ],
      ["logic.switch", "in", { rules: [{ name: "in" }] }, "rules/0/name"],
      ["ai.classify", "other", { categories: [{ name: "other" }] }, "categories/0/name"],
      ["error.handle", "default", { branches: [{ name: "default" }] }, "branches/0/name"],
      ["human.approval", "approved", { choices: [{ id: "approved" }] }, "choices/0/id"],
      ["human.approval", "rejected", { choices: [{ id: "rejected" }] }, "choices/0/id"],
    ];

    it.each(cases)("%s: `%s` is refused on the entry", (definitionId, name, config, field) => {
      const g = graph({ entry: "n", nodes: [node("n", definitionId, config)] });
      const problems = run(g).filter((problem) => problem.code === "port-name-taken");
      expect(problems.map((problem) => [problem.nodeId, problem.field, problem.message])).toEqual([
        ["n", field, `${MESSAGE_KEYS["port-name-taken"]} ${JSON.stringify({ name })}`],
      ]);
    });

    it("`unsure` clashes only when the classifier has a minimum confidence", () => {
      const categories = [{ name: "unsure" }];
      const free = run(graph({ entry: "n", nodes: [node("n", "ai.classify", { categories })] }));
      expect(codesOf(free)).not.toContain("port-name-taken");
      const set = run(
        graph({
          entry: "n",
          nodes: [node("n", "ai.classify", { categories, min_confidence: 0.5 })],
        }),
      );
      expect(codesOf(set)).toContain("port-name-taken");
    });

    it("`error` clashes only on a step that routes its errors", () => {
      const config = { rules: [{ name: "error" }] };
      const plain = node("n", "logic.switch", config);
      expect(codesOf(run(graph({ entry: "n", nodes: [plain] })))).not.toContain("port-name-taken");
      const routing = { ...plain, policy: { on_error: "route" as const } };
      expect(codesOf(run(graph({ entry: "n", nodes: [routing] })))).toContain("port-name-taken");
    });

    it("a step with free names, or a malformed list, has nothing to refuse", () => {
      const nodes = [
        node("a", "logic.switch", { rules: [{ name: "fine" }, "x", null] }),
        node("b", "ai.classify", { categories: "nope" }),
      ];
      expect(codesOf(run(graph({ entry: "a", nodes })))).not.toContain("port-name-taken");
    });
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
      bindings: [literalBinding("branch", "value", true)],
    });
    expect(codesOf(run(g))).toEqual(["merge-together-uncertain"]);
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

  it("rule 8 — a port may feed several steps", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer_noreq")],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "a", "out", "c", "in")],
    });
    expect(run(g)).toEqual([]);
  });

  it("rule 9 — an unbound required input", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("b", "test.consumer")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect(codesOf(run(g))).toEqual(["input-not-bound"]);
  });

  it("rule 9 — an if or a switch with nothing bound to its value", () => {
    for (const id of ["logic.if", "logic.switch"]) {
      const g = graph({
        entry: "entry",
        nodes: [echo("entry"), node("d", id)],
        edges: [edge("e1", "entry", "out", "d", "in")],
      });
      expect(
        run(g)
          .filter((p) => p.code === "decision-value-not-bound")
          .map((p) => [p.nodeId, p.field]),
      ).toEqual([["d", "value"]]);
      expect(codesOf(run({ ...g, bindings: [literalBinding("d", "value", true)] }))).not.toContain(
        "decision-value-not-bound",
      );
      expect(
        codesOf(run({ ...g, bindings: [literalBinding("d", "value/x", true)] })),
      ).not.toContain("decision-value-not-bound");
    }
  });

  it("rule 9 — a required setting left empty, unless it is set or bound", () => {
    const withConfig = (
      config: Record<string, unknown>,
      bindings: ReturnType<typeof literalBinding>[] = [],
    ) =>
      graph({
        entry: "a",
        nodes: [echo("a"), node("b", "test.picks_agent", config)],
        edges: [edge("e1", "a", "out", "b", "in")],
        bindings,
      });
    expect(codesOf(run(withConfig({ note: "x" })))).toEqual(["config-not-set"]);
    expect(run(withConfig({}))[0]?.field).toBe("agent");
    expect(codesOf(run(withConfig({ agent: "ag" })))).toEqual([]);
    expect(codesOf(run(withConfig({}, [literalBinding("b", "agent", "ag")])))).toEqual([]);
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

describe("binding-picker helpers", () => {
  const linear = graph({
    entry: "a",
    nodes: [echo("a"), node("b", "test.consumer_noreq"), node("c", "test.consumer")],
    edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "c", "in")],
  });

  it("computePrecede reports what must have run before a node", () => {
    expect(computePrecede(linear, CATALOG).get("c")).toEqual(new Set(["a", "b", "c"]));
  });

  it("availableSourceNodes is what precedes the node, minus the node itself", () => {
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

function splitNode(id: string, ...names: string[]) {
  return node(id, "logic.split", { branches: names.map((name) => ({ name })) });
}

function routed(id: string, definitionId = "debug.echo") {
  return { ...node(id, definitionId, { message: "hi" }), policy: { on_error: "route" as const } };
}

/** `S.a -> A -> M`, `S.b -> B -> M`, then `after`. */
function mergedFork(mergeConfig: Record<string, unknown> = {}) {
  return graph({
    entry: "entry",
    nodes: [
      echo("entry"),
      splitNode("S", "a", "b"),
      { ...echo("A"), label: "A" },
      { ...echo("B"), label: "B" },
      node("M", "logic.merge", mergeConfig),
      node("after", "test.consumer"),
    ],
    edges: [
      edge("e1", "entry", "out", "S", "in"),
      edge("e2", "S", "a", "A", "in"),
      edge("e3", "S", "b", "B", "in"),
      edge("e4", "A", "out", "M", "in"),
      edge("e5", "B", "out", "M", "in"),
      edge("e6", "M", "out", "after", "in"),
    ],
    bindings: [literalBinding("after", "value", "x")],
  });
}

describe("parallel branches", () => {
  it("publishes a Split whose branches meet at a merge waiting for all", () => {
    expect(run(mergedFork({ wait_for: "all" }))).toEqual([]);
  });

  it("refuses a merge waiting for one behind a Split", () => {
    expect(codesOf(run(mergedFork()))).toEqual(["merge-wait-for-all"]);
  });

  it("refuses a merge waiting for all behind an If, and publishes one waiting for one", () => {
    const g = (config: Record<string, unknown>) =>
      graph({
        entry: "entry",
        nodes: [
          echo("entry"),
          node("branch", "logic.if"),
          { ...echo("A"), label: "A" },
          { ...echo("B"), label: "B" },
          node("M", "logic.merge", config),
        ],
        edges: [
          edge("e1", "entry", "out", "branch", "in"),
          edge("e2", "branch", "then", "A", "in"),
          edge("e3", "branch", "otherwise", "B", "in"),
          edge("e4", "A", "out", "M", "in"),
          edge("e5", "B", "out", "M", "in"),
        ],
        bindings: [literalBinding("branch", "value", true)],
      });
    expect(codesOf(run(g({ wait_for: "all" })))).toEqual(["merge-wait-for-one"]);
    expect(run(g({})).map((p) => p.code)).toEqual([]);
  });

  it("refuses two branches with one name, and a branch with no usable name", () => {
    const keys = ["A", "B"].map((id) => ({ source_node_id: id, source_port: "out", key: "same" }));
    const same = run(mergedFork({ wait_for: "all", branch_keys: keys }));
    expect(codesOf(same)).toEqual(["merge-key-invalid"]);
    expect(same[0]?.field).toBe("branch_keys");
    const g = mergedFork({ wait_for: "all" });
    const unnamed = {
      ...g,
      nodes: g.nodes.map((n) => (n.id === "A" ? { ...n, label: "!!!" } : n)),
    };
    expect(codesOf(run(unnamed))).toEqual(["merge-key-invalid"]);
  });

  it("refuses reading a branch the merge does not have", () => {
    const g = mergedFork({ wait_for: "all" });
    const reading = (key: string) => ({
      ...g,
      bindings: [nodeOutputBinding("after", "value", "M", "out", ["branches", key, "value"])],
    });
    const problems = run(reading("nope")).filter((p) => p.code === "merge-key-unknown");
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({ nodeId: "after", field: "value" });
    expect(problems[0]?.message).toContain('"key":"nope"');
    expect(codesOf(run(reading("a")))).not.toContain("merge-key-unknown");
    const whole = {
      ...g,
      bindings: [nodeOutputBinding("after", "value", "M", "out", ["branches"])],
    };
    expect(codesOf(run(whole))).not.toContain("merge-key-unknown");
    const value = {
      ...g,
      bindings: [nodeOutputBinding("after", "value", "M", "out", ["value", "x"])],
    };
    expect(codesOf(run(value))).not.toContain("merge-key-unknown");
  });

  it.each(["wait_for", "branch_keys", "branch_keys/a"])(
    "refuses binding the Merge setting %s",
    (field) => {
      const g = mergedFork({ wait_for: "all" });
      const bound = { ...g, bindings: [literalBinding("M", field, "all")] };
      const problem = run(bound).find((p) => p.code === "merge-setting-bound");
      expect(problem).toMatchObject({ nodeId: "M", field });
    },
  );

  it("refuses a Split that routes its errors", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), { ...splitNode("S", "a", "b"), policy: { on_error: "route" } }],
      edges: [edge("e1", "entry", "out", "S", "in")],
    });
    const problem = run(g).find((p) => p.code === "split-routes-errors");
    expect(problem).toMatchObject({ nodeId: "S", field: "policy" });
  });

  it("publishes a step fed by legs one of which may turn away", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("W", "logic.switch", { rules: [{ name: "r" }] }),
        echo("A"),
        node("B", "logic.if"),
        echo("J"),
      ],
      edges: [
        edge("e1", "entry", "out", "W", "in"),
        edge("e2", "W", "r", "A", "in"),
        edge("e3", "W", "r", "B", "in"),
        edge("e4", "A", "out", "J", "in"),
        edge("e5", "B", "then", "J", "in"),
      ],
      bindings: [literalBinding("W", "value", 1), literalBinding("B", "value", 1)],
    });
    expect(joinCodes(run(g))).toEqual([]);
  });

  it("refuses two parallel error routes into one handler, and accepts one handler each", () => {
    const fork = (shared: boolean) =>
      graph({
        entry: "entry",
        nodes: [
          echo("entry"),
          splitNode("S", "a", "b"),
          routed("A"),
          routed("B"),
          node("H1", "error.handle"),
          node("H2", "error.handle"),
          echo("after1"),
          echo("after2"),
        ],
        edges: [
          edge("e1", "entry", "out", "S", "in"),
          edge("e2", "S", "a", "A", "in"),
          edge("e3", "S", "b", "B", "in"),
          edge("e4", "A", "error", "H1", "in"),
          edge("e5", "B", "error", shared ? "H1" : "H2", "in"),
          edge("e6", "H1", "default", "after1", "in"),
          edge("e7", "H2", "default", "after2", "in"),
        ],
      });
    const shared = run(fork(true)).filter((p) => p.code === "error-handler-shared");
    expect(shared.map((p) => p.nodeId)).toEqual(["H1"]);
    expect(codesOf(run(fork(false)))).not.toContain("error-handler-shared");
  });

  it("reports an error handler's unwired default beside its shared feed, as the server does", () => {
    const routed = (id: string) => ({ ...echo(id), policy: { on_error: "route" as const } });
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        splitNode("S", "a", "b"),
        routed("A"),
        routed("B"),
        node("H", "error.handle"),
      ],
      edges: [
        edge("e1", "entry", "out", "S", "in"),
        edge("e2", "S", "a", "A", "in"),
        edge("e3", "S", "b", "B", "in"),
        edge("e4", "A", "error", "H", "in"),
        edge("e5", "B", "error", "H", "in"),
      ],
    });
    const found = run(g).filter((p) => p.nodeId === "H");
    expect(found.map((p) => p.code).sort()).toEqual([
      "error-handler-default-unwired",
      "error-handler-shared",
    ]);
  });

  it("reports a step that routes its errors to nowhere", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), { ...echo("A"), policy: { on_error: "route" } }],
      edges: [edge("e1", "entry", "out", "A", "in")],
    });
    expect(run(g)).toContainEqual(
      expect.objectContaining({ nodeId: "A", code: "error-port-unwired" }),
    );
  });

  it.each([
    ["core.output", "outputs-both-run"],
    ["webhook.respond", "respond-both-run"],
  ])("refuses a second %s step that can run beside the first", (definitionId, code) => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        splitNode("S", "a", "b"),
        node("O1", definitionId),
        node("O2", definitionId),
      ],
      edges: [
        edge("e1", "entry", "out", "S", "in"),
        edge("e2", "S", "a", "O1", "in"),
        edge("e3", "S", "b", "O2", "in"),
      ],
    });
    const problems = run(g).filter((p) => p.code === code);
    expect(problems.map((p) => p.nodeId)).toEqual(["O2"]);
  });

  it("publishes two answering steps on the two sides of an If", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("branch", "logic.if"),
        node("O1", "core.output"),
        node("O2", "core.output"),
      ],
      edges: [
        edge("e1", "entry", "out", "branch", "in"),
        edge("e2", "branch", "then", "O1", "in"),
        edge("e3", "branch", "otherwise", "O2", "in"),
      ],
      bindings: [literalBinding("branch", "value", true)],
    });
    expect(run(g)).toEqual([]);
  });

  it("offers both parallel legs as binding sources at their join", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), splitNode("S", "a", "b"), echo("A"), echo("B"), echo("J")],
      edges: [
        edge("e1", "entry", "out", "S", "in"),
        edge("e2", "S", "a", "A", "in"),
        edge("e3", "S", "b", "B", "in"),
        edge("e4", "A", "out", "J", "in"),
        edge("e5", "B", "out", "J", "in"),
      ],
    });
    expect(availableSourceNodes(g, CATALOG, "J")).toEqual(new Set(["entry", "S", "A", "B"]));
    expect(availableSourceNodes(g, CATALOG, "A")).toEqual(new Set(["entry", "S"]));
  });
});

describe("a merge's branch names", () => {
  function keysFor(g: ReturnType<typeof graph>) {
    const definitions = resolveDefinitions(g, CATALOG);
    const merge = g.nodes.find((n) => n.id === "M") as (typeof g.nodes)[number];
    return [...branchKeys(g, definitions, merge).values()];
  }

  it("calls a Split's branch by its name and any other step by its label or name", () => {
    const g = graph({
      entry: "s",
      nodes: [
        splitNode("s", "a", "b"),
        { ...echo("l"), label: "Fetch the data" },
        { ...echo("d"), label: "2nd try" },
        echo("n"),
        { ...echo("long"), label: "x".repeat(40) },
        node("u", "no.such.step"),
        node("M", "logic.merge"),
      ],
      edges: [
        edge("e1", "s", "a", "M", "in"),
        edge("e2", "s", "b", "M", "in"),
        edge("e3", "l", "out", "M", "in"),
        edge("e4", "d", "out", "M", "in"),
        edge("e5", "n", "out", "M", "in"),
        edge("e6", "long", "out", "M", "in"),
        edge("e7", "u", "out", "M", "in"),
      ],
    });
    expect(keysFor(g)).toEqual([
      "a",
      "b",
      "fetch_the_data",
      "b_2nd_try",
      "echo",
      "x".repeat(32),
      "no_such_step",
    ]);
  });

  it("prefers a stored key and ignores a malformed one", () => {
    const base = mergedFork();
    const stored = (branch_keys: unknown) => ({
      ...base,
      nodes: base.nodes.map((n) => (n.id === "M" ? { ...n, config: { branch_keys } } : n)),
    });
    expect(
      keysFor(
        stored([
          { source_node_id: "A", source_port: "out", key: "mine" },
          "not an object",
          { source_node_id: "B", source_port: "out", key: 3 },
        ]),
      ),
    ).toEqual(["mine", "b"]);
    expect(keysFor(stored("nope"))).toEqual(["a", "b"]);
  });

  it("counts a wire once and skips an edge from nowhere", () => {
    const base = mergedFork();
    const g = {
      ...base,
      edges: [
        ...base.edges,
        edge("again", "A", "out", "M", "in"),
        edge("ghost", "nobody", "out", "M", "in"),
      ],
    };
    expect(keysFor(g)).toEqual(["a", "b"]);
  });
});

describe("steps reached from several ports", () => {
  const ifX = () => node("X", "logic.if");
  const decides = literalBinding("X", "value", true);

  it("refuses two outputs after a step reached from both ports of an If", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        ifX(),
        echo("P"),
        echo("T"),
        node("O1", "core.output"),
        node("O2", "core.output"),
      ],
      edges: [
        edge("e1", "entry", "out", "X", "in"),
        edge("e2", "X", "then", "P", "in"),
        edge("e3", "P", "out", "O1", "in"),
        edge("e4", "P", "out", "T", "in"),
        edge("e5", "X", "otherwise", "T", "in"),
        edge("e6", "T", "out", "O2", "in"),
      ],
      bindings: [decides],
    });
    expect(
      run(g)
        .filter((p) => p.code === "outputs-both-run")
        .map((p) => p.nodeId),
    ).toEqual(["O2"]);
  });

  it("refuses a merge waiting for one beside a step reached from both ports", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), ifX(), echo("P"), echo("T"), node("M", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "X", "in"),
        edge("e2", "X", "then", "P", "in"),
        edge("e3", "P", "out", "T", "in"),
        edge("e4", "X", "otherwise", "T", "in"),
        edge("e5", "T", "out", "M", "in"),
        edge("e6", "P", "out", "M", "in"),
      ],
      bindings: [decides],
    });
    expect(codesOf(run(g))).toContain("merge-together-uncertain");
  });

  it("does not let a join read a leg that one port of an If skips", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        ifX(),
        echo("t0"),
        echo("Y"),
        echo("T"),
        node("A", "test.consumer_noreq"),
        node("J", "test.consumer"),
      ],
      edges: [
        edge("e1", "entry", "out", "X", "in"),
        edge("e2", "X", "then", "t0", "in"),
        edge("e3", "X", "otherwise", "Y", "in"),
        edge("e4", "Y", "out", "t0", "in"),
        edge("e5", "t0", "out", "T", "in"),
        edge("e6", "X", "then", "A", "in"),
        edge("e7", "A", "out", "J", "in"),
        edge("e8", "T", "out", "J", "in"),
      ],
      bindings: [decides, nodeOutputBinding("J", "value", "A", "out", ["value"])],
    });
    expect(codesOf(run(g)).filter((code) => code === "binding-unavailable")).toHaveLength(1);
  });
});

describe("a merge's duplicate edges", () => {
  it("are refused whichever way the merge waits", () => {
    const base = mergedFork({ wait_for: "all" });
    const dup = { ...base, edges: [...base.edges, edge("again", "A", "out", "M", "in")] };
    expect(codesOf(run(dup))).toEqual(["merge-duplicate-branch"]);
    const parallel = mergedFork();
    const dupOne = {
      ...parallel,
      edges: [...parallel.edges, edge("again", "A", "out", "M", "in")],
    };
    expect(codesOf(run(dupOne))).toEqual(["merge-duplicate-branch", "merge-wait-for-all"]);
  });
});

describe("a merge judged by run conditions", () => {
  const ifA = (id: string) => node(id, "logic.if");
  const decides = (id: string) => literalBinding(id, "value", true);

  it("publishes a merge after a nested If with a shared else", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), ifA("X"), ifA("Y"), echo("A"), echo("T"), node("M", "logic.merge")],
      edges: [
        edge("e1", "entry", "out", "X", "in"),
        edge("e2", "X", "then", "Y", "in"),
        edge("e3", "Y", "then", "A", "in"),
        edge("e4", "Y", "otherwise", "T", "in"),
        edge("e5", "X", "otherwise", "T", "in"),
        edge("e6", "A", "out", "M", "in"),
        edge("e7", "T", "out", "M", "in"),
      ],
      bindings: [decides("X"), decides("Y")],
    });
    expect(run(g)).toEqual([]);
  });

  it("publishes a merge after a Switch whose cases share a step", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        node("S", "logic.switch", { rules: [{ name: "a" }, { name: "b" }] }),
        echo("Shared"),
        echo("C"),
        node("M", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "S", "in"),
        edge("e2", "S", "a", "Shared", "in"),
        edge("e3", "S", "b", "Shared", "in"),
        edge("e4", "S", "otherwise", "C", "in"),
        edge("e5", "Shared", "out", "M", "in"),
        edge("e6", "C", "out", "M", "in"),
      ],
      bindings: [decides("S")],
    });
    expect(run(g)).toEqual([]);
  });

  it("names a branch that may not arrive at a merge waiting for all", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        splitNode("P", "x", "y"),
        node("S", "logic.switch", { rules: [{ name: "r1" }, { name: "r2" }] }),
        { ...echo("A"), label: "A" },
        { ...echo("B"), label: "B" },
        { ...echo("D"), label: "D" },
        node("M", "logic.merge", { wait_for: "all" }),
      ],
      edges: [
        edge("e1", "entry", "out", "P", "in"),
        edge("e2", "P", "x", "S", "in"),
        edge("e3", "P", "y", "D", "in"),
        edge("e4", "S", "r1", "A", "in"),
        edge("e5", "S", "r2", "B", "in"),
        edge("e6", "A", "out", "M", "in"),
        edge("e7", "B", "out", "M", "in"),
        edge("e8", "D", "out", "M", "in"),
      ],
      bindings: [decides("S")],
    });
    const problems = run(g).filter((p) => p.code === "merge-leg-not-guaranteed");
    expect(problems.map((p) => p.message)).toEqual([
      expect.stringContaining('"name":"a"'),
      expect.stringContaining('"name":"b"'),
    ]);
  });

  it("publishes a merge joining a routed step's out and its handler", () => {
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        { ...echo("R"), policy: { on_error: "route" as const } },
        node("H", "error.handle"),
        node("M", "logic.merge"),
      ],
      edges: [
        edge("e1", "entry", "out", "R", "in"),
        edge("e2", "R", "out", "M", "in"),
        edge("e3", "R", "error", "H", "in"),
        edge("e4", "H", "default", "M", "in"),
      ],
    });
    expect(joinCodes(run(g))).toEqual([]);
  });

  it("publishes a handler fed by two steps that cannot both fail", () => {
    const routedStep = (id: string) => ({
      ...echo(id),
      policy: { on_error: "route" as const },
    });
    const g = graph({
      entry: "entry",
      nodes: [
        echo("entry"),
        ifA("I"),
        routedStep("A"),
        routedStep("B"),
        node("H", "error.handle"),
        echo("after"),
      ],
      edges: [
        edge("e1", "entry", "out", "I", "in"),
        edge("e2", "I", "then", "A", "in"),
        edge("e3", "I", "otherwise", "B", "in"),
        edge("e4", "A", "error", "H", "in"),
        edge("e5", "B", "error", "H", "in"),
        edge("e6", "H", "default", "after", "in"),
      ],
      bindings: [decides("I")],
    });
    expect(codesOf(run(g))).not.toContain("error-handler-shared");
  });

  it("publishes an action fed from both outcomes of an If without a merge", () => {
    const g = graph({
      entry: "entry",
      nodes: [echo("entry"), ifA("I"), echo("A"), echo("B"), echo("J")],
      edges: [
        edge("e1", "entry", "out", "I", "in"),
        edge("e2", "I", "then", "A", "in"),
        edge("e3", "I", "otherwise", "B", "in"),
        edge("e4", "A", "out", "J", "in"),
        edge("e5", "B", "out", "J", "in"),
      ],
      bindings: [decides("I")],
    });
    expect(joinCodes(run(g))).toEqual([]);
  });
});
