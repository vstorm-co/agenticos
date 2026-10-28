import { describe, expect, it } from "vitest";

import {
  DEBUG_ECHO,
  echo,
  edge,
  graph,
  makeCatalog,
  makeDefinition,
  node,
  nodeOutputBinding,
} from "./fixtures";
import { resolveDefinitions } from "./topology";
import { quickLogProblems, rule13NamedAndSwitchedOffSteps } from "./rules";

const DECIDE = makeDefinition({ id: "logic.if", kind: "control" });
const catalog = makeCatalog([DEBUG_ECHO, DECIDE]);
const codes = (g: Parameters<typeof rule13NamedAndSwitchedOffSteps>[0]) =>
  rule13NamedAndSwitchedOffSteps(g, resolveDefinitions(g, catalog)).map((problem) => [
    problem.nodeId,
    problem.code,
  ]);

describe("rule 13 - names and switched-off steps", () => {
  it("lets steps share nothing but an empty name, ignoring case", () => {
    const g = graph({
      entry: "a",
      nodes: [
        { ...echo("a"), label: "Tidy" },
        { ...echo("b"), label: " tidy " },
        { ...echo("c"), label: "  " },
        echo("d"),
      ],
    });
    expect(codes(g)).toEqual([["b", "label-taken"]]);
  });

  it("keeps the trigger and a deciding step on, and nothing reading a step that is off", () => {
    const g = graph({
      entry: "a",
      nodes: [
        { ...echo("a"), disabled: true },
        { ...node("b", "logic.if"), disabled: true },
        { ...echo("c"), disabled: true },
        echo("d"),
      ],
      bindings: [nodeOutputBinding("d", "value", "c", "out", ["message"])],
    });
    expect(codes(g)).toEqual([
      ["a", "trigger-switched-off"],
      ["b", "control-switched-off"],
      ["d", "binding-reads-switched-off"],
    ]);
  });

  it("lets a step read one that is off when what comes into it has the field", () => {
    const through = (first: ReturnType<typeof echo>, extra: ReturnType<typeof edge>[] = []) =>
      graph({
        entry: "a",
        nodes: [first, { ...echo("c"), disabled: true }, echo("d"), echo("x")],
        edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "c", "out", "d", "in"), ...extra],
        bindings: [nodeOutputBinding("d", "value", "c", "out", ["echoed"])],
      });
    // The trigger's `echoed` goes through the step that is off.
    expect(codes(through(echo("a")))).toEqual([]);
    // Two ways in: which one it would hand on is not known.
    expect(codes(through(echo("a"), [edge("e3", "x", "out", "c", "in")]))).toEqual([
      ["d", "binding-reads-switched-off"],
    ]);
  });

  it("refuses the read when what comes in is off too, or lacks the field", () => {
    const g = graph({
      entry: "a",
      nodes: [
        echo("a"),
        { ...echo("b"), disabled: true },
        { ...echo("c"), disabled: true },
        echo("d"),
      ],
      edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "c", "in")],
      bindings: [
        nodeOutputBinding("d", "value", "c", "out", ["echoed"]),
        nodeOutputBinding("d", "message", "b", "out", ["message"]),
      ],
    });
    expect(codes(g)).toEqual([
      ["d", "binding-reads-switched-off"],
      ["d", "binding-reads-switched-off"],
    ]);
  });
});

describe("a quick log's outputs", () => {
  const check = (g: Parameters<typeof quickLogProblems>[0]) =>
    quickLogProblems(g, resolveDefinitions(g, catalog)).map((problem) => [
      problem.nodeId,
      problem.field,
      problem.code,
      problem.params,
    ]);

  it("refuses an output the step lacks, and `error` unless the step routes errors", () => {
    const g = graph({
      entry: "a",
      nodes: [
        { ...echo("a"), quick_log: { message: "m", outputs: ["out", "nope"] } },
        { ...echo("b"), quick_log: { message: "m", outputs: ["error"] } },
        {
          ...echo("c"),
          policy: { on_error: "route" },
          quick_log: { message: "m", outputs: ["error"] },
        },
        { ...echo("d"), quick_log: { message: "m", outputs: null } },
        echo("e"),
      ],
    });
    expect(check(g)).toEqual([
      ["a", "quick_log/outputs/1", "quick-log-output-unknown", { name: "nope" }],
      ["b", "quick_log/outputs/0", "quick-log-output-unknown", { name: "error" }],
    ]);
  });
});

describe("what a quick log may not say", () => {
  const LOOP_ITEM = makeDefinition({ id: "loop.item", kind: "control" });
  const loopCatalog = makeCatalog([DEBUG_ECHO, LOOP_ITEM]);
  const check = (g: Parameters<typeof quickLogProblems>[0]) =>
    quickLogProblems(g, resolveDefinitions(g, loopCatalog)).map((problem) => [
      problem.nodeId,
      problem.field,
      problem.code,
      problem.params,
    ]);
  const logged = (id: string, message: string, outputs: string[] | null = null) => ({
    ...echo(id),
    quick_log: { message, outputs },
  });

  it("is refused on a loop's item and yield steps, whatever else it holds", () => {
    const item = {
      ...node("i", "loop.item"),
      quick_log: { message: "{{error.details}}", outputs: [] },
    };
    const yielded = { ...node("y", "loop.yield"), quick_log: { message: "m", outputs: null } };
    const g = graph({ entry: "i", nodes: [item, yielded] });
    expect(check(g)).toEqual([
      ["i", "quick_log", "quick-log-not-here", undefined],
      ["y", "quick_log", "quick-log-not-here", undefined],
    ]);
  });

  it("refuses an empty list of outputs, but not a missing one", () => {
    const g = graph({
      entry: "a",
      nodes: [logged("a", "m", []), logged("b", "m", null)],
    });
    expect(check(g)).toEqual([["a", "quick_log/outputs", "quick-log-no-outputs", undefined]]);
  });

  it("reads an error's code and message and nothing else of it", () => {
    const g = graph({
      entry: "a",
      nodes: [
        logged("a", "{{error.code}} {{ error.message }} {{error_code}} {{error2.x}} {{step}}"),
        logged("b", "{{error}} and {{error.details}} and {{error.code.deep}}"),
      ],
    });
    expect(check(g)).toEqual([
      ["b", "quick_log/message", "quick-log-error-reference", { reference: "error" }],
      ["b", "quick_log/message", "quick-log-error-reference", { reference: "error.details" }],
      ["b", "quick_log/message", "quick-log-error-reference", { reference: "error.code.deep" }],
    ]);
  });
});
