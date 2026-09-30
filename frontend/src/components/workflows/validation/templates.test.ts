import { describe, expect, it } from "vitest";

import type { Binding, NodeOutputRef, WorkflowGraph } from "@/lib/workflows/types";

import { DEBUG_ECHO, echo, edge, graph, makeCatalog, makeDefinition, port } from "./fixtures";
import {
  danglingReferences,
  rule3TypeCompatibility,
  rule4BranchLocalAvailability,
  rule6NestedScopeBoundaries,
  rule13NamedAndSwitchedOffSteps,
  templateTargets,
} from "./rules";
import { resolveDefinitions } from "./topology";

/** A template's placeholders are checked like bindings; the field it fills must take text. */

const NUMBERED = makeDefinition({
  id: "test.numbered",
  input_schema: { type: "object", properties: { count: { type: "integer" } } },
  ports: [port("in", "input", null), port("out", "output", null)],
});
const catalog = makeCatalog([DEBUG_ECHO, NUMBERED]);

function ref(nodeId: string, ...path: string[]): NodeOutputRef {
  return { kind: "node_output", node_id: nodeId, port: "out", field_path: path };
}

function template(target: string, field: string, ...parts: (string | NodeOutputRef)[]): Binding {
  return { target_node_id: target, target_field: field, source: { kind: "template", parts } };
}

/** The binding problems only: the echo-to-echo edge these graphs share is not what is tested. */
const codes = (problems: { code: string }[]) =>
  problems.map((problem) => problem.code).filter((code) => code.startsWith("binding"));

function line(bindings: Binding[]): WorkflowGraph {
  return graph({
    entry: "a",
    nodes: [echo("a"), echo("b")],
    edges: [edge("e", "a", "out", "b", "in")],
    bindings,
  });
}

describe("a template's placeholders", () => {
  it("must each name a step of the graph", () => {
    expect(codes(danglingReferences(line([template("b", "message", "Hi ", ref("x"))])))).toEqual([
      "binding-source-node-missing",
    ]);
  });

  it("must each name a field the step hands on, of any type", () => {
    const g = line([
      template(
        "b",
        "message",
        ref("a", "echoed"),
        " at ",
        ref("a", "received_at"),
        ref("a", "nope"),
      ),
    ]);
    expect(codes(rule3TypeCompatibility(g, resolveDefinitions(g, catalog)))).toEqual([
      "binding-field-path-unknown",
    ]);
  });

  it("must each read a step that has run, in the same scope, that is not switched off", () => {
    // `message` is not in what reaches `b`, so switched off it hands on nothing.
    const g = {
      ...line([template("a", "message", ref("b", "message"))]),
      nodes: [echo("a"), { ...echo("b"), disabled: true }],
    };
    const dominators = new Map([["a", new Set(["a"])]]);
    expect(codes(rule4BranchLocalAvailability(g, dominators))).toEqual(["binding-unavailable"]);
    expect(codes(rule6NestedScopeBoundaries(g, [], new Map([["b", "loop"]])))).toEqual([
      "binding-crosses-scope",
    ]);
    expect(codes(rule13NamedAndSwitchedOffSteps(g, resolveDefinitions(g, catalog)))).toEqual([
      "binding-reads-switched-off",
    ]);
  });
});

describe("the field a template fills", () => {
  it("must take text", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), { ...echo("n"), definition_id: "test.numbered" }, echo("u")],
      bindings: [
        template("a", "message", "fine"),
        template("n", "count", "Hi"),
        template("gone", "x", "Hi"),
        { target_node_id: "a", target_field: "message", source: { kind: "literal", value: "x" } },
      ],
    });
    const problems = templateTargets(g, resolveDefinitions(g, catalog));
    expect(problems.map((problem) => [problem.nodeId, problem.code])).toEqual([
      ["n", "binding-template-not-text"],
    ]);
  });
});
