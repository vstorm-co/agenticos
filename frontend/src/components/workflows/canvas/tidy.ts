import type {
  NodeDefinition,
  NodeInstance,
  NodePosition,
  Uuid,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { stepFootprint } from "./node-size";

const GAP_X = 80;
const GAP_Y = 32;

/**
 * Where each step in view goes when the graph is tidied: left to right by how
 * far it is from where the flow starts, stacked in each column in the order
 * they stood, the columns centred on one another.
 *
 * A step's column is its longest path from a step nothing leads into, so every
 * wire runs rightwards. A graph with a loop in it - never publishable, but a
 * draft can hold one - keeps the steps the loop holds in their first column.
 * The first column stays where the flow's first step was, so tidying moves the
 * graph as little as it can. A column is as wide as its widest step and a step
 * takes the height it was given, so a resized step pushes its neighbours.
 * Only `x` and `y` are returned; a step keeps its size.
 */
export function tidyLayout(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): Map<Uuid, NodePosition> {
  const ids = new Set(graph.nodes.map((node) => node.id));
  const edges = graph.edges.filter(
    (edge) => ids.has(edge.source_node_id) && ids.has(edge.target_node_id),
  );
  const incoming = new Map<Uuid, number>(graph.nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    incoming.set(edge.target_node_id, (incoming.get(edge.target_node_id) ?? 0) + 1);
  }
  const column = new Map<Uuid, number>();
  const queue = graph.nodes.filter((node) => incoming.get(node.id) === 0).map((node) => node.id);
  for (const id of queue) column.set(id, 0);
  while (queue.length > 0) {
    const id = queue.shift() as Uuid;
    for (const edge of edges.filter((item) => item.source_node_id === id)) {
      const next = edge.target_node_id;
      column.set(next, Math.max(column.get(next) ?? 0, (column.get(id) ?? 0) + 1));
      const left = (incoming.get(next) ?? 0) - 1;
      incoming.set(next, left);
      if (left === 0) queue.push(next);
    }
  }

  const columns = new Map<number, { node: NodeInstance; height: number; width: number }[]>();
  for (const node of graph.nodes) {
    const at = column.get(node.id) ?? 0;
    const { width, height } = stepFootprint(node, definitions.get(node.id) ?? null, graph.bindings);
    columns.set(at, [...(columns.get(at) ?? []), { node, width, height }]);
  }
  const first = graph.nodes.find((node) => node.id === graph.entry_node_id) ?? graph.nodes[0];
  const origin = first?.layout ?? { x: 0, y: 0 };
  const layouts = new Map<Uuid, NodePosition>();
  let left = origin.x;
  for (const [, items] of [...columns.entries()].sort(([a], [b]) => a - b)) {
    const stacked = [...items].sort((a, b) => a.node.layout.y - b.node.layout.y);
    const total =
      stacked.reduce((sum, item) => sum + item.height, 0) + (stacked.length - 1) * GAP_Y;
    let top = origin.y - total / 2;
    for (const [index, { node, height }] of stacked.entries()) {
      // The first card sits half its own height below the column's top: a lone card stays put.
      if (index === 0) top += height / 2;
      layouts.set(node.id, { x: left, y: top });
      top += height + GAP_Y;
    }
    left += Math.max(...stacked.map((item) => item.width)) + GAP_X;
  }
  return layouts;
}
