import { describe, expect, it } from "vitest";

import type { NodeDefinition, NodeInstance, Port } from "@/lib/workflows/types";

import { cardHeight, NODE_HEIGHT, NODE_WIDTH, stepFootprint, textLines } from "./node-size";

function step(definitionId: string, extra: Partial<NodeInstance> = {}): NodeInstance {
  return {
    id: "n",
    definition_id: definitionId,
    definition_version: 1,
    config: {},
    layout: { x: 0, y: 0 },
    ...extra,
  };
}

function definition(
  id: string,
  outputs: string[] = ["out"],
  kind: NodeDefinition["kind"] = "action",
): NodeDefinition {
  const ports = [
    { id: "in", label: "in", kind: "input" },
    ...outputs.map((out) => ({ id: out, label: out, kind: "output" })),
  ] as unknown as Port[];
  return { id, version: 1, name: id, kind, ports } as unknown as NodeDefinition;
}

describe("cardHeight", () => {
  it("is 60 px for a step with no summary line, 16 more with one, known or not", () => {
    expect(cardHeight(step("x"), definition("x"), [], false)).toBe(60);
    expect(cardHeight(step("x"), null, [], false)).toBe(60);
    expect(cardHeight(step("x"), definition("x"), [], true)).toBe(76);
    // Placement does not know whether the card draws one, and leaves it in.
    expect(cardHeight(step("x"), definition("x"), [])).toBe(76);
  });

  it("adds a waits band, labelled output rows and a loop's enter row", () => {
    expect(cardHeight(step("human.approval"), definition("human.approval"), [])).toBe(76 + 22);
    // Two outputs, or an error one, are labelled rows: 13 + 16 each + 2 between.
    expect(cardHeight(step("x"), definition("x", ["a", "b"]), [])).toBe(76 + 13 + 32 + 2);
    expect(cardHeight(step("x"), definition("x", ["out", "error"]), [])).toBe(76 + 47);
    // The enter row: a 1 px rule, 16 px of padding and a 28 px button.
    const loop = definition("control.foreach", ["body"], "control");
    expect(cardHeight(step("control.foreach"), loop, [], false)).toBe(60 + 45);
  });

  it("adds a row of policy badges, and a second one once all three no longer fit", () => {
    const withPolicy = (policy: NodeInstance["policy"], definitionId = definition("x")) =>
      cardHeight(step("x", { policy }), definitionId, [], false);
    expect(withPolicy({ timeout_seconds: 30 })).toBe(60 + 28.5);
    expect(withPolicy({ retry: { max_attempts: 3 } } as NodeInstance["policy"])).toBe(60 + 28.5);
    expect(withPolicy({ on_error: "route" })).toBe(60 + 28.5);
    expect(withPolicy({ retry: { max_attempts: 1 } } as NodeInstance["policy"])).toBe(60);
    expect(withPolicy(null)).toBe(60);
    // Timeout, retry and routes-errors together wrap onto a second row.
    expect(
      withPolicy({
        timeout_seconds: 30,
        retry: { max_attempts: 3 },
        on_error: "route",
      } as NodeInstance["policy"]),
    ).toBe(60 + 28.5 + 22.5);
  });
});

describe("stepFootprint", () => {
  it("is the size a step was given, else the default width and its natural height", () => {
    expect(stepFootprint(step("x"), definition("x"), [])).toEqual({
      width: NODE_WIDTH,
      height: 76,
    });
    const sized = step("x", { layout: { x: 0, y: 0, width: 320, height: 200 } });
    expect(stepFootprint(sized, definition("x"), [])).toEqual({ width: 320, height: 200 });
    expect(NODE_HEIGHT).toBeGreaterThan(76);
  });
});

describe("textLines", () => {
  it("gives one line each at the default size, or any size at or under the natural height", () => {
    expect(textLines(undefined, 76)).toEqual({ name: 1, summary: 1 });
    expect(textLines(60, 76)).toEqual({ name: 1, summary: 1 });
    expect(textLines(76, 76)).toEqual({ name: 1, summary: 1 });
  });

  it("gives the extra height to the name first, then to the summary, to their caps", () => {
    expect(textLines(76 + 19, 76)).toEqual({ name: 1, summary: 1 });
    expect(textLines(76 + 20, 76)).toEqual({ name: 2, summary: 1 });
    expect(textLines(76 + 40, 76)).toEqual({ name: 3, summary: 1 });
    expect(textLines(76 + 55, 76)).toEqual({ name: 3, summary: 1 });
    expect(textLines(76 + 56, 76)).toEqual({ name: 3, summary: 2 });
    expect(textLines(400, 76)).toEqual({ name: 3, summary: 2 });
  });
});
