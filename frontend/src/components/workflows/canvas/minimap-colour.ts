import type { Node } from "@xyflow/react";

import { nodeFamily } from "@/components/workflows/node-visuals";

import type { WorkflowNodeData } from "./graph-adapter";

/** A step's mark on the minimap: its family's colour, from the `--family-map-*` tokens. A note is a Flow-grey mark. */
export function minimapColour(node: Node): string {
  const category =
    node.type === "note" ? "" : ((node.data as WorkflowNodeData).definition?.category ?? "");
  return `var(--family-map-${nodeFamily(category)})`;
}
