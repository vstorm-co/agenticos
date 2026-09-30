import { describe, expect, it } from "vitest";

import {
  DEBUG_ECHO,
  echo,
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
});
