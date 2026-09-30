import type { NodePosition, Uuid, WorkflowGraph } from "@/lib/workflows/types";

import { NODE_HEIGHT, NODE_WIDTH } from "./insertion";

const GAP_X = 80;
const GAP_Y = 40;

/**
 * Where each step in view goes when the graph is tidied: left to right by how
 * far it is from where the flow starts, stacked in each column in the order
 * they stood, the columns centred on one another.
 *
 * A step's column is its longest path from a step nothing leads into, so every
 * wire runs rightwards. A graph with a loop in it - never publishable, but a
 * draft can hold one - keeps the steps the loop holds in their first column.
 * The first column stays where the flow's first step was, so tidying moves the
 * graph as little as it can.
 */
export function tidyLayout(graph: WorkflowGraph): Map<Uuid, NodePosition> {
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

  const columns = new Map<number, typeof graph.nodes>();
  for (const node of graph.nodes) {
    const at = column.get(node.id) ?? 0;
    columns.set(at, [...(columns.get(at) ?? []), node]);
  }
  const first = graph.nodes.find((node) => node.id === graph.entry_node_id) ?? graph.nodes[0];
  const origin = first?.layout ?? { x: 0, y: 0 };
  const layouts = new Map<Uuid, NodePosition>();
  for (const [at, nodes] of columns) {
    const stacked = [...nodes].sort((a, b) => a.layout.y - b.layout.y);
    const height = stacked.length * NODE_HEIGHT + (stacked.length - 1) * GAP_Y;
    stacked.forEach((node, index) => {
      layouts.set(node.id, {
        x: origin.x + at * (NODE_WIDTH + GAP_X),
        y: origin.y - height / 2 + NODE_HEIGHT / 2 + index * (NODE_HEIGHT + GAP_Y),
      });
    });
  }
  return layouts;
}
