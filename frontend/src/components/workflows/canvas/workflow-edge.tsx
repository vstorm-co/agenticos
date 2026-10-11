"use client";

import { BaseEdge, type EdgeProps, getBezierPath } from "@xyflow/react";
import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import type { KeyboardEvent, MouseEvent } from "react";

import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import type { EdgeVariant, WorkflowFlowEdge } from "./graph-adapter";
import { useNodeRunSummary } from "./run-overlay";

/** The stroke each edge variant draws with — data muted, error red, branch accented. */
const VARIANT_CLASS: Record<EdgeVariant, string> = {
  data: "!stroke-muted-foreground",
  error: "!stroke-destructive",
  branch: "!stroke-primary",
};

/**
 * A typed workflow edge: a bezier path styled by its variant, with a control
 * node's branch labelled on the wire - and, on a run's canvas, how many items
 * went along it when the step before handed on a list.
 *
 * The variant and label are computed once during projection (`edgeVariant`) and
 * ride in `data`; the label is drawn by `<BaseEdge>` itself (an SVG text node,
 * no portal), so the component is testable without a mounted `<ReactFlow>`.
 *
 * A selected edge is drawn heavier and carries a delete button on the wire, so the
 * reader can tell it is selected and has a way to remove it besides knowing the
 * Backspace shortcut. The button removes the edge through the store, the same path
 * xyflow's delete key takes, so history and autosave see one ordinary edit. An
 * edge is only ever selected on an editable canvas, so the button never shows on a
 * published version.
 */
export function WorkflowEdge({
  id,
  source,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  selected,
  data,
}: EdgeProps<WorkflowFlowEdge>) {
  const t = useTranslations("workflows");
  const applyEdgeChanges = useWorkflowEditorStore((state) => state.applyEdgeChanges);
  const beginSplit = useWorkflowEditorStore((state) => state.beginSplit);
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const variant = data?.variant ?? "data";
  // On a run's canvas, how many items the step before handed along this wire.
  const items = useNodeRunSummary(source)?.items ?? null;
  const counted = items === null ? null : t("edgeItems", { count: items });
  const label = [data?.label, counted].filter(Boolean).join(" · ") || undefined;

  // Removing the edge removes the button that holds focus, so hand focus back to the
  // canvas region the shortcuts listen on, or Cmd+Z right after deleting does nothing.
  const remove = (button: Element) => {
    const region = button.closest<HTMLElement>('[data-workflow-region="canvas"]');
    applyEdgeChanges([{ id, type: "remove" }]);
    region?.focus();
  };
  // The click would otherwise reach the edge underneath and select it again.
  const onClick = (event: MouseEvent) => {
    event.stopPropagation();
    remove(event.currentTarget);
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    event.stopPropagation();
    remove(event.currentTarget);
  };
  // A branch label sits on the wire's midpoint; the button goes just below it.
  const buttonY = label ? labelY + 18 : labelY;

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={VARIANT_CLASS[variant]}
        style={selected ? { strokeWidth: 3 } : undefined}
        label={label ?? undefined}
        labelX={labelX}
        labelY={labelY}
      />
      {selected && (
        <g
          role="button"
          tabIndex={0}
          aria-label={t("deleteConnection")}
          transform={`translate(${labelX}, ${buttonY})`}
          // xyflow gives every edge `pointer-events: visibleStroke`, which the button
          // inherits: only its outline would take a click, and the disc would let one
          // fall through to the edge underneath.
          className="pointer-events-auto cursor-pointer"
          onClick={onClick}
          onKeyDown={onKeyDown}
        >
          <circle r={11} className="fill-background stroke-border" strokeWidth={1.5} />
          <X x={-5} y={-5} width={10} height={10} className="stroke-foreground" />
        </g>
      )}
      {selected && (
        <g
          role="button"
          tabIndex={0}
          aria-label={t("insertOnConnection")}
          transform={`translate(${labelX - 28}, ${buttonY})`}
          className="pointer-events-auto cursor-pointer"
          onClick={(event) => {
            event.stopPropagation();
            beginSplit(id);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            event.stopPropagation();
            beginSplit(id);
          }}
        >
          <circle r={11} className="fill-background stroke-border" strokeWidth={1.5} />
          <Plus x={-5} y={-5} width={10} height={10} className="stroke-foreground" />
        </g>
      )}
    </>
  );
}

/** The one custom edge type the canvas registers. */
export const edgeTypes = {
  workflow: WorkflowEdge,
};
