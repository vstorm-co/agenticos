import { describe, expect, it } from "vitest";

import { edge, graph, literalBinding, node } from "@/components/workflows/validation/fixtures";

import { diffGraphs } from "./graph-diff";

describe("diffGraphs", () => {
  it("says which steps were added and removed, and draws both", () => {
    const before = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("gone", "debug.echo")],
      edges: [edge("e1", "a", "out", "gone", "in")],
    });
    const after = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("new", "debug.echo")],
      edges: [edge("e2", "a", "out", "new", "in")],
    });

    const diff = diffGraphs(before, after);

    expect(Object.fromEntries(diff.steps)).toEqual({
      new: { change: "added", fields: [] },
      gone: { change: "removed", fields: [] },
    });
    expect([diff.edgesAdded, diff.edgesRemoved]).toEqual([1, 1]);
    expect(diff.union.nodes.map((n) => n.id)).toEqual(["a", "new", "gone"]);
    // Drawn below the step that took its place, not over it.
    expect(diff.union.nodes[2]?.layout).toEqual({ x: 0, y: 120 });
    expect(diff.union.edges.map((e) => e.id)).toEqual(["e2", "e1"]);
  });

  it("lists every field a changed step changed in, and nothing it merely moved", () => {
    const was = node("s", "debug.echo", { message: "hi", keep: { b: 1, a: 2 } });
    const now = {
      ...node("s", "debug.echo", { message: "hello", keep: { a: 2, b: 1 }, extra: 1 }, 2),
      label: "Greet",
      notes: "Say hello",
      disabled: true,
      policy: { timeout_seconds: 5 },
      layout: { x: 400, y: 90 },
      pinned_output: { echoed: "x" },
    };
    const before = graph({ entry: "s", nodes: [was], bindings: [literalBinding("s", "a", 1)] });
    const after = graph({
      entry: "s",
      nodes: [now as typeof was],
      bindings: [literalBinding("s", "a", 2), literalBinding("s", "b", 1)],
    });

    expect(diffGraphs(before, after).steps.get("s")).toEqual({
      change: "changed",
      fields: [
        { kind: "version" },
        { kind: "name" },
        { kind: "note" },
        { kind: "switchedOff" },
        { kind: "whenItFails" },
        { kind: "setting", name: "extra" },
        { kind: "setting", name: "message" },
        { kind: "input", name: "a" },
        { kind: "input", name: "b" },
      ],
    });
  });

  it("leaves a removed step where it stood when nothing took its place", () => {
    const far = { ...node("far", "debug.echo"), layout: { x: 900, y: 0 } };
    const before = graph({ entry: "a", nodes: [node("a", "debug.echo"), far] });
    const after = graph({ entry: "a", nodes: [node("a", "debug.echo")] });
    expect(diffGraphs(before, after).union.nodes[1]).toBe(far);
  });

  it("finds nothing between a graph and itself moved about", () => {
    const before = graph({ entry: "a", nodes: [node("a", "debug.echo", { list: [1, null] })] });
    const after = graph({
      entry: "a",
      nodes: [{ ...node("a", "debug.echo", { list: [1, null] }), layout: { x: 9, y: 9 } }],
    });
    const diff = diffGraphs(before, after);
    expect([diff.steps.size, diff.edgesAdded, diff.edgesRemoved]).toEqual([0, 0, 0]);
  });
});
