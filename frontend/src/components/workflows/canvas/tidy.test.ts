import { describe, expect, it } from "vitest";

import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { NODE_WIDTH } from "./node-size";
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

    const layouts = tidyLayout(graph, new Map());
    const step = NODE_WIDTH + 80;

    expect(layouts.get("a")).toEqual({ x: 10, y: 20 });
    expect(layouts.get("d")).toEqual({ x: 10 + 2 * step, y: 20 });
    // Two in the middle column, kept in the order they stood and centred on the start.
    const [b, c] = [layouts.get("b")!, layouts.get("c")!];
    expect([b.x, c.x]).toEqual([10 + step, 10 + step]);
    // A card with a summary line is 76 px tall, and a gap of 32 sits between rows.
    expect(c.y - b.y).toBe(76 + 32);
    expect((b.y + c.y) / 2).toBe(20);
  });

  it("stacks two-port cards, which are taller than a plain one, clear of one another", () => {
    // 76 for a plain card, and two labelled ports add 47: 123, near an If's measured 123.
    const TWO_PORTS = 123;
    const twoOutputs = {
      ports: [
        { id: "in", label: "in", kind: "input" },
        { id: "yes", label: "yes", kind: "output" },
        { id: "no", label: "no", kind: "output" },
      ],
    } as unknown as NodeDefinition;
    const graph: WorkflowGraph = {
      entry_node_id: "start",
      nodes: [at("start", 0, 0), at("approval", 0, 0), at("if", 0, 50)],
      edges: [wire("start", "approval"), wire("start", "if")],
      bindings: [],
      scopes: [],
    };
    const layouts = tidyLayout(
      graph,
      new Map([
        ["approval", twoOutputs],
        ["if", twoOutputs],
      ]),
    );
    const approval = layouts.get("approval")!;
    const second = layouts.get("if")!;

    expect(second.y - approval.y - TWO_PORTS).toBeGreaterThanOrEqual(8);
  });

  it("keeps a loop's steps in the first column, and starts an empty graph nowhere", () => {
    const looped: WorkflowGraph = {
      entry_node_id: "gone",
      nodes: [at("a", 0, 0), at("b", 0, 0)],
      edges: [wire("a", "b"), wire("b", "a")],
      bindings: [],
      scopes: [],
    };
    expect([...tidyLayout(looped, new Map()).values()].map((layout) => layout.x)).toEqual([0, 0]);
    expect(
      tidyLayout({ entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] }, new Map())
        .size,
    ).toBe(0);
  });

  it("gives a wide step's column the room it needs, and a tall step's neighbours theirs", () => {
    const sized = (id: string, width: number, height: number): NodeInstance => ({
      ...at(id, 0, 0),
      layout: { x: 0, y: 0, width, height },
    });
    const graph: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [sized("a", 500, 300), at("b", 0, 0), at("c", 0, 10)],
      edges: [wire("a", "b"), wire("a", "c")],
      bindings: [],
      scopes: [],
    };
    const layouts = tidyLayout(graph, new Map());
    const [b, c] = [layouts.get("b")!, layouts.get("c")!];

    // The next column starts past the wide step and the gap, and nothing is resized by tidying.
    expect(b.x).toBe(500 + 80);
    expect(layouts.get("a")).toEqual({ x: 0, y: 0 });
    expect(Object.keys(layouts.get("a")!)).toEqual(["x", "y"]);
    expect(c.y - b.y).toBe(76 + 32);

    const tall: WorkflowGraph = {
      entry_node_id: "a",
      nodes: [at("a", 0, 0), sized("b", 240, 300), at("c", 0, 10)],
      edges: [wire("a", "b"), wire("a", "c")],
      bindings: [],
      scopes: [],
    };
    const [tallB, tallC] = [
      tidyLayout(tall, new Map()).get("b")!,
      tidyLayout(tall, new Map()).get("c")!,
    ];
    expect(tallC.y - tallB.y).toBe(300 + 32);
  });
});
