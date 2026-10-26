import { describe, expect, it } from "vitest";

import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { NODE_WIDTH, ROW_HEIGHT } from "./insertion";
import { tidyLayout } from "./tidy";

const at = (id: string, x: number, y: number): NodeInstance => ({
  id,
  definition_id: "step",
  definition_version: 1,
  config: {},
  layout: { x, y },
});
const wire = (source: string, target: string) => ({
  id: `${source}-${target}`,
  source_node_id: source,
  source_port: "out",
  target_node_id: target,
  target_port: "in",
});

describe("tidyLayout", () => {
  it("lines steps up left to right by how far they are from the start", () => {
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [at("a", 10, 20), at("c", 5, 900), at("b", 700, -50), at("d", 0, 0)],
      edges: [wire("a", "b"), wire("a", "c"), wire("b", "d"), wire("c", "d"), wire("x", "d")],
      bindings: [],
      scopes: [],
    };

    const layouts = tidyLayout(graph);
    const step = NODE_WIDTH + 80;

    expect(layouts.get("a")).toEqual({ x: 10, y: 20 });
    expect(layouts.get("d")).toEqual({ x: 10 + 2 * step, y: 20 });
    // Two in the middle column, kept in the order they stood and centred on the start.
    const [b, c] = [layouts.get("b")!, layouts.get("c")!];
    expect([b.x, c.x]).toEqual([10 + step, 10 + step]);
    expect(c.y - b.y).toBe(ROW_HEIGHT + 32);
    expect((b.y + c.y) / 2).toBe(20);
  });

  it("stacks two-port cards, an Approval over an If, clear of one another", () => {
    // Heights from the card's classes: 24 padding + 14 label + 20 name + 16 summary + 2 border
    // = 76 for a plain card, 22 more for a waits band, and two labelled ports (47) can be
    // taller than the text beside them. An Approval is about 129 px, an If with a condition 123.
    const APPROVAL = 129;
    const IF = 123;
    const graph: WorkflowGraph = {
      entry_node_id: "start",
      nodes: [at("start", 0, 0), at("approval", 0, 0), at("if", 0, 50)],
      edges: [wire("start", "approval"), wire("start", "if")],
      bindings: [],
      scopes: [],
    };
    const layouts = tidyLayout(graph);
    const approval = layouts.get("approval")!;
    const second = layouts.get("if")!;

    expect(second.y - approval.y - APPROVAL).toBeGreaterThanOrEqual(8);
    // The same holds either way round: the pitch clears the taller card.
    expect(second.y - approval.y - IF).toBeGreaterThanOrEqual(8);
  });

  it("keeps a loop's steps in the first column, and starts an empty graph nowhere", () => {
    const looped: WorkflowGraph = {
      entry_node_id: "gone",
      nodes: [at("a", 0, 0), at("b", 0, 0)],
      edges: [wire("a", "b"), wire("b", "a")],
      bindings: [],
      scopes: [],
    };
    expect([...tidyLayout(looped).values()].map((layout) => layout.x)).toEqual([0, 0]);
    expect(
      tidyLayout({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] }).size,
    ).toBe(0);
  });
});
