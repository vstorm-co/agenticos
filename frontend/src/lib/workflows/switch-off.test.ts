import { describe, expect, it } from "vitest";

import {
  DEBUG_ECHO,
  echo,
  edge,
  graph,
  makeDefinition,
  node,
} from "@/components/workflows/validation/fixtures";

import { canSwitchOff, isLoopPart, isWired } from "./switch-off";

const DECIDE = makeDefinition({ id: "logic.if", kind: "control" });
const LOOP_RESULT = makeDefinition({ id: "loop.yield", kind: "control" });

describe("canSwitchOff", () => {
  const g = graph({
    entry: "a",
    nodes: [echo("a"), node("wired", "logic.if"), node("parked", "logic.if"), echo("b")],
    edges: [edge("e1", "a", "out", "wired", "in")],
  });
  const find = (id: string) => g.nodes.find((n) => n.id === id)!;

  it("offers any step that is not the trigger and does not decide the way", () => {
    expect(canSwitchOff(g, find("b"), DEBUG_ECHO)).toBe(true);
    expect(canSwitchOff(g, find("b"), null)).toBe(true);
  });

  it("keeps the trigger on", () => {
    expect(canSwitchOff(g, find("a"), DEBUG_ECHO)).toBe(false);
  });

  it("offers a step that decides the way only while it has no connection", () => {
    expect(canSwitchOff(g, find("wired"), DECIDE)).toBe(false);
    expect(canSwitchOff(g, find("parked"), DECIDE)).toBe(true);
  });

  it("keeps a loop's item and result steps on, wired or not", () => {
    const result = node("result", "loop.yield");
    expect(canSwitchOff({ ...g, nodes: [...g.nodes, result] }, result, LOOP_RESULT)).toBe(false);
  });

  it("always offers to switch a step that is off back on", () => {
    expect(canSwitchOff(g, { ...find("wired"), disabled: true }, DECIDE)).toBe(true);
    expect(canSwitchOff(g, { ...find("a"), disabled: true }, DEBUG_ECHO)).toBe(true);
  });
});

describe("isLoopPart and isWired", () => {
  it("names a loop's item and result steps and nothing else", () => {
    expect(isLoopPart("loop.item")).toBe(true);
    expect(isLoopPart("loop.yield")).toBe(true);
    expect(isLoopPart("control.foreach")).toBe(false);
  });

  it("counts a connection at either end", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), echo("b"), echo("c")],
      edges: [edge("e1", "a", "out", "b", "in")],
    });
    expect([isWired(g, "a"), isWired(g, "b"), isWired(g, "c")]).toEqual([true, true, false]);
  });
});

it("keeps non-default triggers on too, with or without catalog metadata", () => {
  const extra = node("other", "trigger.manual");
  const g = graph({ entry: "a", nodes: [echo("a"), extra] });
  expect(canSwitchOff(g, extra, makeDefinition({ id: "trigger.manual", kind: "action" }))).toBe(
    false,
  );
  expect(canSwitchOff(g, extra, null)).toBe(false);
});
