"use client";

import { CirclePause, CirclePlay, Copy, Settings2, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
} from "@/components/ui";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { copyToClipboard, pasteFromClipboard } from "./use-canvas-shortcuts";

/**
 * A step's right-click menu: open it, duplicate it, switch it off or on, delete
 * it. A right click on the empty canvas opens the step picker instead
 * (`PanePicker`).
 */
export function CanvasContextMenu({
  nodeId,
  catalog,
}: {
  /** The step that was right-clicked. */
  nodeId: string;
  catalog: NodeDefinition[];
}) {
  const t = useTranslations("workflows");
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const applyNodeChanges = useWorkflowEditorStore((state) => state.applyNodeChanges);
  const updateNodeDetails = useWorkflowEditorStore((state) => state.updateNodeDetails);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const store = useWorkflowEditorStore.getState;
  const node = graph?.nodes.find((candidate) => candidate.id === nodeId);
  const definition = catalog.find(
    (item) => item.id === node?.definition_id && item.version === node?.definition_version,
  );
  // The trigger and a step that decides the way cannot be skipped.
  const switchable =
    node !== undefined && node.id !== graph?.entry_node_id && definition?.kind !== "control";
  return (
    <ContextMenuContent className="w-56">
      <ContextMenuItem onSelect={() => editNode(nodeId)}>
        <Settings2 />
        {t("menuOpenSettings")}
        <ContextMenuShortcut>↵</ContextMenuShortcut>
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => {
          copyToClipboard(store());
          pasteFromClipboard(store());
        }}
      >
        <Copy />
        {t("menuDuplicate")}
      </ContextMenuItem>
      {switchable && (
        <ContextMenuItem onSelect={() => updateNodeDetails(node.id, { disabled: !node.disabled })}>
          {node.disabled ? <CirclePlay /> : <CirclePause />}
          {node.disabled ? t("menuSwitchOn") : t("menuSwitchOff")}
        </ContextMenuItem>
      )}
      <ContextMenuSeparator />
      <ContextMenuItem
        variant="destructive"
        onSelect={() => applyNodeChanges([{ type: "remove", id: nodeId }])}
      >
        <Trash2 />
        {t("nodeEditorDelete")}
        <ContextMenuShortcut>⌫</ContextMenuShortcut>
      </ContextMenuItem>
    </ContextMenuContent>
  );
}
