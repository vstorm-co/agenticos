import { setAside } from "@/components/workflows/validation/topology";
import type { WorkflowGraph } from "@/lib/workflows/types";

import { NodeRunStatusLabel } from "./run-status";

/** Parked steps have no node-run row, but remain inspectable in the run's graph. */
export function SetAsideSteps({
  graph,
  nameOf,
  onInspect,
}: {
  graph: WorkflowGraph | null;
  nameOf: (nodeId: string) => string;
  onInspect: (nodeId: string) => void;
}) {
  if (graph === null) return null;
  const parked = setAside(graph);
  return graph.nodes
    .filter((step) => parked.has(step.id))
    .map((step) => (
      <li key={`aside-${step.id}`} className="py-2">
        <button
          type="button"
          className="hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left outline-none focus-visible:ring-2"
          onClick={() => onInspect(step.id)}
        >
          <span className="min-w-0 truncate text-sm font-medium">{nameOf(step.id)}</span>
          <NodeRunStatusLabel status="skipped" switchedOff />
        </button>
      </li>
    ));
}
