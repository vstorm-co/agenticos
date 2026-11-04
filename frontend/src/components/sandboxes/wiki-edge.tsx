"use client";

import { BaseEdge, useInternalNode, type EdgeProps } from "@xyflow/react";
import type { WikiFlowNode } from "@/lib/wiki-flow";

/** Links meet the coloured dots, independently of their larger pointer targets. */
export function WikiEdge({ id, source, target, markerEnd, style }: EdgeProps) {
  const from = useInternalNode<WikiFlowNode>(source);
  const to = useInternalNode<WikiFlowNode>(target);
  if (!from || !to) return null;
  const a = from.internals.positionAbsolute,
    b = to.internals.positionAbsolute;
  const dx = b.x - a.x,
    dy = b.y - a.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const start = from.data.radius / distance,
    end = to.data.radius / distance;
  const path = `M ${a.x + 10 + dx * start},${a.y + 10 + dy * start} L ${b.x + 10 - dx * end},${b.y + 10 - dy * end}`;
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={8} />;
}
