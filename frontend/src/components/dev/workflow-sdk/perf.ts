import type { WorkflowGraph } from "./typed-graph";

/**
 * A linear chain of `count` nodes with a binding in each: the shape that makes an
 * editor do the same work per node a real workflow would (a form-backed node, an
 * edge, a binding). Deterministic so two runs load the same document.
 */
export function syntheticGraph(count: number): WorkflowGraph {
  const nodes: WorkflowGraph["nodes"] = [];
  const edges: WorkflowGraph["edges"] = [];
  const perRow = 10;
  for (let index = 0; index < count; index += 1) {
    const id = `n${index}`;
    const position = { x: (index % perRow) * 300, y: Math.floor(index / perRow) * 140 };
    nodes.push(
      index % 2 === 0
        ? {
            id,
            label: `Agent ${index}`,
            position,
            config: {
              kind: "agent",
              agent_id: "",
              version_id: "",
              prompt: `Use {{ n${Math.max(0, index - 1)}.output }}`,
            },
          }
        : {
            id,
            label: `Write ${index}`,
            position,
            config: {
              kind: "table_write",
              table_id: "tbl-invoices",
              mode: "upsert",
              key_column: "invoice_no",
              batch_size: 100,
              mappings: [{ column: "amount", value: `{{ n${index - 1}.output.amount }}` }],
              on_conflict: {},
            },
          },
    );
    if (index > 0) edges.push({ id: `e${index}`, source: `n${index - 1}`, target: id });
  }
  return { nodes, edges };
}
