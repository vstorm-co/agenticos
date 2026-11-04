import { effectiveDefinition } from "@/lib/workflows/ports";
import type { NodeDefinition, NodeInstance } from "@/lib/workflows/types";

/**
 * What a step's output ports are called on the canvas, by port id: the ids a log
 * line carries are the ports', and a reader knows the ports by their labels. A
 * port whose label is its id, or none, is left out.
 */
export function outcomeLabels(
  instance: NodeInstance,
  definition: NodeDefinition | undefined,
): Map<string, string> {
  const labels = new Map<string, string>();
  if (definition === undefined) return labels;
  for (const port of effectiveDefinition(instance, definition).ports) {
    if (port.kind === "output" && port.label && port.label !== port.id) {
      labels.set(port.id, port.label);
    }
  }
  return labels;
}
