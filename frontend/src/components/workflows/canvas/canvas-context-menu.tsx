"use client";

import { CirclePause, CirclePlay, Copy, RotateCcw, Settings2, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
} from "@/components/ui";
import { canSwitchOff } from "@/lib/workflows/switch-off";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { copyToClipboard, usePasteFromClipboard } from "./use-canvas-shortcuts";

/**
 * A step's right-click menu: open it, duplicate it, switch it off or on, put it
 * back to its default size, delete it. A right click on the empty canvas opens
 * the step picker instead (`PanePicker`).
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
  const resizeNode = useWorkflowEditorStore((state) => state.resizeNode);
  const updateNodeDetails = useWorkflowEditorStore((state) => state.updateNodeDetails);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const store = useWorkflowEditorStore.getState;
  const paste = usePasteFromClipboard(catalog);
  const node = graph?.nodes.find((candidate) => candidate.id === nodeId);
  const definition = catalog.find(
    (item) => item.id === node?.definition_id && item.version === node?.definition_version,
  );
  const switchable = node !== undefined && graph != null && canSwitchOff(graph, node, definition);
  const sized = node !== undefined && (node.layout.width != null || node.layout.height != null);
  // A loop's Loop item and Loop result go only with their loop: never deleted or copied alone.
  const loopPart = definition?.loop_body_only === true;
  return (
    <ContextMenuContent className="w-56">
      <ContextMenuItem onSelect={() => editNode(nodeId)}>
        <Settings2 />
        {t("menuOpenSettings")}
        <ContextMenuShortcut>↵</ContextMenuShortcut>
      </ContextMenuItem>
      {!loopPart && (
        <ContextMenuItem
          onSelect={() => {
            copyToClipboard(store());
            paste();
          }}
        >
          <Copy />
          {t("menuDuplicate")}
        </ContextMenuItem>
      )}
      {switchable && (
        <ContextMenuItem onSelect={() => updateNodeDetails(node.id, { disabled: !node.disabled })}>
          {node.disabled ? <CirclePlay /> : <CirclePause />}
          {node.disabled ? t("menuSwitchOn") : t("menuSwitchOff")}
        </ContextMenuItem>
      )}
      {sized && (
        <ContextMenuItem onSelect={() => resizeNode(nodeId, null)}>
          <RotateCcw />
          {t("menuResetSize")}
        </ContextMenuItem>
      )}
      {!loopPart && (
        <>
          <ContextMenuSeparator />
          <ContextMenuItem
            variant="destructive"
            onSelect={() => applyNodeChanges([{ type: "remove", id: nodeId }])}
          >
            <Trash2 />
            {t("nodeEditorDelete")}
            <ContextMenuShortcut>⌫</ContextMenuShortcut>
          </ContextMenuItem>
        </>
      )}
    </ContextMenuContent>
  );
}
