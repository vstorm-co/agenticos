"use client";

import { BaseEdge, type EdgeProps, getBezierPath } from "@xyflow/react";

import type { EdgeVariant, WorkflowFlowEdge } from "./graph-adapter";

/** The stroke each edge variant draws with — data muted, error red, branch accented. */
const VARIANT_CLASS: Record<EdgeVariant, string> = {
  data: "!stroke-muted-foreground",
  error: "!stroke-destructive",
  branch: "!stroke-primary",
};

/**
 * A typed workflow edge: a bezier path styled by its variant, with a control
 * node's branch labelled on the wire.
 *
 * The variant and label are computed once during projection (`edgeVariant`) and
 * ride in `data`; the label is drawn by `<BaseEdge>` itself (an SVG text node,
 * no portal), so the component is testable without a mounted `<ReactFlow>`.
 */
export function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<WorkflowFlowEdge>) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const variant = data?.variant ?? "data";
  const label = data?.label;

  return (
    <BaseEdge
      id={id}
      path={path}
      markerEnd={markerEnd}
      className={VARIANT_CLASS[variant]}
      label={label ?? undefined}
      labelX={labelX}
      labelY={labelY}
    />
  );
}

/** The one custom edge type the canvas registers. */
export const edgeTypes = {
  workflow: WorkflowEdge,
};
