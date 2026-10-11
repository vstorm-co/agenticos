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
import { rule13NamedAndSwitchedOffSteps } from "./rules";

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
