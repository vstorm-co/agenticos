"use client";

import { createContext, useContext, useMemo } from "react";
import {
  MiniMap,
  getBezierPath,
  Position,
  useEdges,
  useNodes,
  useReactFlow,
  type Edge,
  type MiniMapNodeProps,
  type Node,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";
import { minimapColour } from "./minimap-colour";
import { NODE_HEIGHT, NODE_WIDTH } from "./node-size";

const Wires = createContext<ReadonlyMap<string, readonly string[]>>(new Map());

/** Keep wires in canvas coordinates so dragging, resizing and saved layouts agree. */
export function minimapWires(
  nodes: readonly Node[],
  edges: readonly Edge[],
): Map<string, string[]> {
  const byId = new Map(nodes.filter((node) => !node.hidden).map((node) => [node.id, node]));
  const paths = new Map<string, string[]>();
  for (const edge of edges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (edge.hidden || !source || !target) continue;
    const [path] = getBezierPath({
      sourceX:
        source.position.x +
        (source.measured?.width ?? source.width ?? source.initialWidth ?? NODE_WIDTH),
      sourceY:
        source.position.y +
        (source.measured?.height ?? source.height ?? source.initialHeight ?? NODE_HEIGHT) / 2,
      targetX: target.position.x,
      targetY:
        target.position.y +
        (target.measured?.height ?? target.height ?? target.initialHeight ?? NODE_HEIGHT) / 2,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    });
    const incoming = paths.get(target.id) ?? [];
    incoming.push(path);
    paths.set(target.id, incoming);
  }
  return paths;
}

function OverviewNode({ id, x, y, width, height, color, className, selected }: MiniMapNodeProps) {
  const wires = useContext(Wires);
  const note = className === "note";
  const radius = className === "trigger" ? height / 2 : 10;
  return (
    <g>
      {wires.get(id)?.map((path, index) => (
        <path
          key={index}
          d={path}
          fill="none"
          stroke="var(--color-muted-foreground)"
          strokeOpacity={0.55}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          pointerEvents="none"
        />
      ))}
      <g>
        <rect
          className="react-flow__minimap-node"
          x={x}
          y={y}
          width={width}
          height={height}
          rx={radius}
          style={{
            fill: "var(--color-card)",
            stroke: selected ? "var(--color-foreground)" : "var(--color-muted-foreground)",
            strokeOpacity: selected ? 0.9 : 0.5,
            strokeWidth: selected ? 1.5 : 0.65,
          }}
          vectorEffect="non-scaling-stroke"
        />
        <rect
          x={x + 12}
          y={y + 12}
          width={note ? width - 24 : 28}
          height={note ? 5 : Math.min(28, height - 24)}
          rx={note ? 2 : 6}
          fill={color || "var(--color-muted-foreground)"}
        />
        {!note && (
          <path
            d={`M${x + 52},${y + height / 2}h${Math.max(12, width - 72)}`}
            stroke="var(--color-muted-foreground)"
            strokeOpacity={0.5}
            strokeWidth={5}
            strokeLinecap="round"
          />
        )}
      </g>
    </g>
  );
}

export function WorkflowMinimap() {
  const t = useTranslations("workflows");
  const { setCenter, getZoom } = useReactFlow();
  const nodes = useNodes();
  const edges = useEdges();
  const style = useWorkflowNodeStyleStore((state) => state.style);
  const wires = useMemo(() => minimapWires(nodes, edges), [nodes, edges]);
  return (
    <Wires.Provider value={wires}>
      <MiniMap
        pannable
        zoomable
        position="bottom-left"
        ariaLabel={t("minimapLabel")}
        onClick={(_, point) => void setCenter(point.x, point.y, { zoom: getZoom() })}
        nodeComponent={OverviewNode}
        nodeClassName={(node) => node.type ?? "action"}
        nodeColor={style === "colour" ? minimapColour : "var(--color-muted-foreground)"}
        maskColor="color-mix(in srgb, var(--color-background) 65%, transparent)"
        maskStrokeColor="color-mix(in srgb, var(--color-foreground) 40%, transparent)"
        maskStrokeWidth={1}
        offsetScale={12}
        style={{ width: 220, height: 140 }}
        className="!bg-background !mb-14 !overflow-hidden !rounded-xl !border shadow-sm"
      />
    </Wires.Provider>
  );
}
