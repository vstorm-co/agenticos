"use client";

import { useMemo } from "react";
import {
  CirclePause,
  CirclePlay,
  Clipboard,
  Copy,
  Maximize,
  Redo2,
  Settings2,
  StickyNote,
  Trash2,
  Undo2,
} from "lucide-react";
import { useTranslations } from "next-intl";

import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@/components/ui";
import {
  type NodeVisual,
  groupVisual,
  nodeVisual,
  operationVisual,
} from "@/components/workflows/node-visuals";
import { isAddableInScope } from "@/components/workflows/palette/scope";
import { pickerSections } from "@/components/workflows/picker";
import type { NodeDefinition } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { copyToClipboard, pasteFromClipboard } from "./use-canvas-shortcuts";

/** What was right-clicked: a step, or the canvas itself. */
export type MenuTarget = { kind: "node"; nodeId: string } | { kind: "pane" };

interface CanvasMenuProps {
  target: MenuTarget;
  catalog: NodeDefinition[];
  /** Add a step where the canvas was right-clicked. */
  onAdd: (definition: NodeDefinition) => void;
  /** Put a note where the canvas was right-clicked; absent inside a loop body. */
  onAddNote?: () => void;
  onFitView: () => void;
}

function Tile({ visual }: { visual: NodeVisual }) {
  const Icon = visual.icon;
  return (
    <span
      className={cn("flex size-5 shrink-0 items-center justify-center rounded", visual.tileClass)}
    >
      <Icon aria-hidden="true" className="size-3" />
    </span>
  );
}

/**
 * The canvas's right-click menu - a step's own actions on a step, and on the
 * canvas every step there is to add, placed where the click was, beside undo,
 * redo, paste and fitting the graph to the view.
 *
 * Steps are listed the way the step picker lists them - sections, then groups
 * such as Slack, then a group's steps - so a builder finds one in the same
 * place whichever way they add it.
 */
export function CanvasContextMenu({
  target,
  catalog,
  onAdd,
  onAddNote,
  onFitView,
}: CanvasMenuProps) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const clipboard = useWorkflowEditorStore((state) => state.clipboard);
  const history = useWorkflowEditorStore((state) => state.history);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const applyNodeChanges = useWorkflowEditorStore((state) => state.applyNodeChanges);
  const updateNodeDetails = useWorkflowEditorStore((state) => state.updateNodeDetails);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const sections = useMemo(
    () => pickerSections(catalog.filter((definition) => isAddableInScope(definition, scopePath))),
    [catalog, scopePath],
  );
  const label = (category: string) =>
    t.has(`category.${category}`) ? t(`category.${category}`) : category;

  if (target.kind === "node") {
    const store = useWorkflowEditorStore.getState;
    const node = graph?.nodes.find((candidate) => candidate.id === target.nodeId);
    const definition = catalog.find(
      (item) => item.id === node?.definition_id && item.version === node?.definition_version,
    );
    // The trigger and a step that decides the way cannot be skipped.
    const switchable =
      node !== undefined && node.id !== graph?.entry_node_id && definition?.kind !== "control";
    return (
      <ContextMenuContent className="w-56">
        <ContextMenuItem onSelect={() => editNode(target.nodeId)}>
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
          <ContextMenuItem
            onSelect={() => updateNodeDetails(node.id, { disabled: !node.disabled })}
          >
            {node.disabled ? <CirclePlay /> : <CirclePause />}
            {node.disabled ? t("menuSwitchOn") : t("menuSwitchOff")}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem
          variant="destructive"
          onSelect={() => applyNodeChanges([{ type: "remove", id: target.nodeId }])}
        >
          <Trash2 />
          {t("nodeEditorDelete")}
          <ContextMenuShortcut>⌫</ContextMenuShortcut>
        </ContextMenuItem>
      </ContextMenuContent>
    );
  }

  const step = (definition: NodeDefinition, visual: NodeVisual) => (
    <ContextMenuItem
      key={`${definition.id}@${definition.version}`}
      onSelect={() => onAdd(definition)}
    >
      <Tile visual={visual} />
      <span className="truncate">{definition.name}</span>
    </ContextMenuItem>
  );

  return (
    <ContextMenuContent className="w-60">
      <ContextMenuLabel>{t("menuAddHere")}</ContextMenuLabel>
      {sections.map((section) => (
        <ContextMenuSub key={section.id}>
          <ContextMenuSubTrigger>{t(`pickerSection.${section.id}`)}</ContextMenuSubTrigger>
          <ContextMenuSubContent className="w-64">
            {section.groups.map((group) => {
              if (group.items.length === 1) {
                const only = group.items[0] as NodeDefinition;
                return step(only, nodeVisual(only.id, only.category));
              }
              return (
                <ContextMenuSub key={group.category}>
                  <ContextMenuSubTrigger>
                    <Tile visual={groupVisual(group.category)} />
                    <span className="truncate">{label(group.category)}</span>
                  </ContextMenuSubTrigger>
                  <ContextMenuSubContent className="w-64">
                    {group.items.map((item) => step(item, operationVisual(item.id, item.category)))}
                  </ContextMenuSubContent>
                </ContextMenuSub>
              );
            })}
          </ContextMenuSubContent>
        </ContextMenuSub>
      ))}
      {onAddNote && (
        <ContextMenuItem onSelect={onAddNote}>
          <StickyNote />
          {t("menuAddNote")}
        </ContextMenuItem>
      )}
      <ContextMenuSeparator />
      <ContextMenuItem
        disabled={clipboard === null}
        onSelect={() => pasteFromClipboard(useWorkflowEditorStore.getState())}
      >
        <Clipboard />
        {t("menuPaste")}
        <ContextMenuShortcut>⌘V</ContextMenuShortcut>
      </ContextMenuItem>
      <ContextMenuItem
        disabled={!history.canUndo}
        onSelect={() => useWorkflowEditorStore.getState().undo()}
      >
        <Undo2 />
        {t("menuUndo")}
        <ContextMenuShortcut>⌘Z</ContextMenuShortcut>
      </ContextMenuItem>
      <ContextMenuItem
        disabled={!history.canRedo}
        onSelect={() => useWorkflowEditorStore.getState().redo()}
      >
        <Redo2 />
        {t("menuRedo")}
        <ContextMenuShortcut>⇧⌘Z</ContextMenuShortcut>
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem onSelect={onFitView}>
        <Maximize />
        {t("menuFitView")}
      </ContextMenuItem>
    </ContextMenuContent>
  );
}
