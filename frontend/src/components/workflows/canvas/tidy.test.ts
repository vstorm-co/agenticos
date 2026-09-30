import { describe, expect, it } from "vitest";

import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { NODE_HEIGHT, NODE_WIDTH } from "./insertion";
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
    expect(c.y - b.y).toBe(NODE_HEIGHT + 40);
    expect((b.y + c.y) / 2).toBe(20);
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
