import { outputFieldNames } from "@/components/workflows/validation/schema";
import type { StepData } from "@/lib/workflows/step-data";
import type { NodeCatalog, Uuid, WorkflowGraph } from "@/lib/workflows/types";

import { isRecord } from "./schema-model";

/** What `path` reaches inside `value`, or undefined when it reaches nothing. */
function reach(value: unknown, path: readonly string[]): unknown {
  let current = value;
  for (const part of path) {
    if (!isRecord(current)) return undefined;
    current = current[part];
  }
  return current;
}

/**
 * The keys a code step's `args` will have: a literal's own keys, or the keys of
 * the output it is bound to - as the last test run saw them, else as the source
 * step declares them. None when `args` is bound to nothing that says.
 */
export function argKeysOf(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
  stepData: Record<Uuid, StepData>,
  nodeId: Uuid,
): string[] {
  const binding = graph.bindings.find(
    (candidate) => candidate.target_node_id === nodeId && candidate.target_field === "args",
  );
  const source = binding?.source;
  if (source === undefined) return [];
  if (source.kind === "literal") return isRecord(source.value) ? Object.keys(source.value) : [];
  if (source.kind !== "node_output") return [];
  const seen = reach(stepData[source.node_id]?.output, source.field_path);
  if (isRecord(seen)) return Object.keys(seen);
  const node = graph.nodes.find((candidate) => candidate.id === source.node_id);
  const definition = catalog.items.find(
    (candidate) =>
      candidate.id === node?.definition_id && candidate.version === node.definition_version,
  );
  return definition === undefined
    ? []
    : outputFieldNames(definition, source.port, source.field_path);
}
