"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";
import { useTranslations } from "next-intl";

import { ownsAScope } from "@/components/workflows/palette";
import { nodeDisplayName, type Port, shortNodeId } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useCanvasInteraction } from "./canvas-context";
import { isErrorPort, type WorkflowFlowNode } from "./graph-adapter";

/** The left border accent that distinguishes the three catalog kind buckets. */
const KIND_ACCENT: Record<"action" | "control" | "waiting", string> = {
  action: "border-l-primary",
  control: "border-l-amber-500",
  waiting: "border-l-sky-500",
};

/**
 * One workflow node on the canvas — the single component every catalog `kind`
 * bucket renders through (`nodeTypes` maps all three to it), differing only by
 * the accent it reads from its definition and the handles it lays out.
 *
 * `Port.kind` places each handle directly — inputs on the left, outputs on the
 * right — rather than inferring direction from a port-id convention; the error
 * output gets a visually distinct handle. Read-only mode (a published version)
 * still mounts every port handle — an edge references its ports by id, so with no
 * handle to position against xyflow draws nothing (error 008) — but makes them
 * non-interactive (`isConnectable={false}`, pointer events off) and drops the
 * keyboard connect controls, matching `nodesConnectable`.
 * Beside the pointer-only handles, every output starts and every input completes
 * a keyboard connection through a real, labelled button — one per port, so a
 * control node's error and branch outputs are reachable, not just the first.
 */
export function WorkflowNode({ data }: NodeProps<WorkflowFlowNode>) {
  const t = useTranslations("workflows");
  const { instance, definition, readOnly } = data;
  const { connectSource, beginConnect, completeConnect } = useCanvasInteraction();
  const enterScope = useWorkflowEditorStore((state) => state.enterScope);

  const kind = definition?.kind ?? "action";
  // A `control.foreach`-shaped node owns a body; its card offers the way in, and
  // the breadcrumb is the way back out. Entering is a display switch (`enterScope`
  // pushes the scope path), never a graph edit.
  const scopeOwner = definition !== null && ownsAScope(definition);
  const name = nodeDisplayName(definition?.name ?? instance.definition_id, instance.id);
  const inputs: Port[] = definition?.ports.filter((port) => port.kind === "input") ?? [];
  const outputs: Port[] = definition?.ports.filter((port) => port.kind === "output") ?? [];
  const connecting = connectSource !== null;

  return (
    <div
      data-node-id={instance.id}
      data-node-kind={kind}
      className={cn(
        "bg-card text-card-foreground min-w-[10rem] rounded-lg border border-l-4 px-3 py-2 shadow-sm",
        KIND_ACCENT[kind],
      )}
    >
      {inputs.map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="target"
          position={Position.Left}
          isConnectable={!readOnly}
          data-port-id={port.id}
          data-port-variant="input"
          className={cn("!bg-muted-foreground", readOnly && "!pointer-events-none")}
        />
      ))}

      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{name}</span>
        <span className="text-muted-foreground font-mono text-[0.65rem]">
          {shortNodeId(instance.id)}
        </span>
      </div>

      {!readOnly &&
        !connecting &&
        outputs.map((port) => (
          <button
            key={port.id}
            type="button"
            aria-label={t("connectFrom", { name, port: port.label })}
            onClick={() => beginConnect({ nodeId: instance.id, portId: port.id })}
            className="text-muted-foreground hover:text-foreground mt-1 block text-xs underline"
          >
            {t("connectStart", { port: port.label })}
          </button>
        ))}
      {!readOnly &&
        connectSource !== null &&
        connectSource.nodeId !== instance.id &&
        inputs.map((port) => (
          <button
            key={port.id}
            type="button"
            aria-label={t("connectTo", { name, port: port.label })}
            onClick={() => completeConnect(connectSource, { nodeId: instance.id, portId: port.id })}
            className="text-primary mt-1 block text-xs underline"
          >
            {t("connectFinish", { port: port.label })}
          </button>
        ))}

      {!readOnly && scopeOwner && (
        <button
          type="button"
          aria-label={t("enterScope", { name })}
          onClick={() => enterScope(instance.id)}
          className="text-muted-foreground hover:text-foreground mt-1 block text-xs underline"
        >
          {t("enterScopeLabel")}
        </button>
      )}

      {outputs.map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="source"
          position={Position.Right}
          isConnectable={!readOnly}
          data-port-id={port.id}
          data-port-variant={isErrorPort(port) ? "error" : "output"}
          className={cn(
            isErrorPort(port) ? "!bg-destructive" : "!bg-primary",
            readOnly && "!pointer-events-none",
          )}
        />
      ))}
    </div>
  );
}

/** Every catalog kind bucket renders through {@link WorkflowNode}. */
export const nodeTypes = {
  action: WorkflowNode,
  control: WorkflowNode,
  waiting: WorkflowNode,
};
