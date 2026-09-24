"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";
import { useTranslations } from "next-intl";

import { nodeDisplayName, type Port, shortNodeId } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

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
 * drops every handle and the connect controls, matching `nodesConnectable`.
 * Beside the pointer-only handles, every output starts and every input completes
 * a keyboard connection through a real, labelled button.
 */
export function WorkflowNode({ data }: NodeProps<WorkflowFlowNode>) {
  const t = useTranslations("workflows");
  const { instance, definition, readOnly } = data;
  const { connectSource, beginConnect, completeConnect } = useCanvasInteraction();

  const kind = definition?.kind ?? "action";
  const name = nodeDisplayName(definition?.name ?? instance.definition_id, instance.id);
  const inputs: Port[] = definition?.ports.filter((port) => port.kind === "input") ?? [];
  const outputs: Port[] = definition?.ports.filter((port) => port.kind === "output") ?? [];
  const outputForConnect = outputs[0];
  const inputForConnect = inputs[0];
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
      {!readOnly &&
        inputs.map((port) => (
          <Handle
            key={port.id}
            id={port.id}
            type="target"
            position={Position.Left}
            data-port-id={port.id}
            data-port-variant="input"
            className="!bg-muted-foreground"
          />
        ))}

      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{name}</span>
        <span className="text-muted-foreground font-mono text-[0.65rem]">
          {shortNodeId(instance.id)}
        </span>
      </div>

      {!readOnly && outputForConnect !== undefined && !connecting && (
        <button
          type="button"
          aria-label={t("connectFrom", { name })}
          onClick={() => beginConnect({ nodeId: instance.id, portId: outputForConnect.id })}
          className="text-muted-foreground hover:text-foreground mt-1 text-xs underline"
        >
          {t("connectStart")}
        </button>
      )}
      {!readOnly &&
        inputForConnect !== undefined &&
        connectSource !== null &&
        connectSource.nodeId !== instance.id && (
          <button
            type="button"
            aria-label={t("connectTo", { name })}
            onClick={() =>
              completeConnect(connectSource, { nodeId: instance.id, portId: inputForConnect.id })
            }
            className="text-primary mt-1 text-xs underline"
          >
            {t("connectFinish")}
          </button>
        )}

      {!readOnly &&
        outputs.map((port) => (
          <Handle
            key={port.id}
            id={port.id}
            type="source"
            position={Position.Right}
            data-port-id={port.id}
            data-port-variant={isErrorPort(port) ? "error" : "output"}
            className={cn(isErrorPort(port) ? "!bg-destructive" : "!bg-primary")}
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
