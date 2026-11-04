"use client";

import { Handle, Position, useViewport, type NodeProps } from "@xyflow/react";
import type { WikiFlowNode } from "@/lib/wiki-flow";

export function WikiNode({ data, selected }: NodeProps<WikiFlowNode>) {
  const { zoom } = useViewport();
  const labelVisible = selected || data.showLabels || zoom >= 1.1;
  return (
    <div className="relative flex size-5 items-center justify-center" title={data.page.title}>
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="!pointer-events-none !size-px !border-0 !opacity-0"
      />
      <span
        className="block shrink-0 rounded-full transition-shadow"
        style={{
          width: data.radius * 2,
          height: data.radius * 2,
          background: data.colour,
          boxShadow: selected ? `0 0 0 4px ${data.colour}25` : undefined,
        }}
      />
      <span
        className="text-foreground pointer-events-none absolute left-1/2 max-w-48 origin-top truncate text-center text-[11px] leading-4 transition-opacity"
        style={{
          opacity: labelVisible ? 0.85 : 0,
          top: data.radius + 15,
          transform: `translateX(-50%) scale(${1 / zoom})`,
        }}
      >
        {data.page.title}
      </span>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="!pointer-events-none !size-px !border-0 !opacity-0"
      />
    </div>
  );
}
