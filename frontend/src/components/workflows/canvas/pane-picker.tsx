"use client";

import { useMemo } from "react";
import { Clipboard, StickyNote } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui";
import { isAddableInScope } from "@/components/workflows/palette/scope";
import { NodePicker } from "@/components/workflows/picker";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { pasteFromClipboard } from "./use-canvas-shortcuts";

/** Where on the canvas the picker opens, in pixels from the canvas's top left. */
export interface PanePoint {
  x: number;
  y: number;
}

/**
 * The step picker a right click on the empty canvas opens, where the click was -
 * the one the "+" opens, so a step is found the same way however it is added -
 * with a note and the clipboard beneath it. The step is placed at that point.
 */
export function PanePicker({
  at,
  catalog,
  onClose,
  onPick,
  onAddNote,
}: {
  /** Open at this point, or closed. */
  at: PanePoint | null;
  catalog: NodeDefinition[];
  onClose: () => void;
  onPick: (definition: NodeDefinition) => void;
  /** Put a note there; absent inside a loop body, which holds no notes. */
  onAddNote?: () => void;
}) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const clipboard = useWorkflowEditorStore((state) => state.clipboard);
  const offered = useMemo(
    () => catalog.filter((definition) => isAddableInScope(definition, scopePath)),
    [catalog, scopePath],
  );
  const act = (action: () => void) => () => {
    action();
    onClose();
  };

  return (
    <Popover open={at !== null} onOpenChange={(open) => !open && onClose()}>
      <PopoverAnchor asChild>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute size-0"
          style={{ left: at?.x ?? 0, top: at?.y ?? 0 }}
        />
      </PopoverAnchor>
      <PopoverContent
        side="right"
        align="start"
        className="w-[22rem] p-0"
        // Focus goes to the step just added, not back to the canvas behind.
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <NodePicker
          offered={offered}
          draggable
          onPick={(definition) => act(() => onPick(definition))()}
        />
        {(onAddNote !== undefined || clipboard !== null) && (
          <div className="border-border flex items-center gap-1 border-t p-1.5">
            {onAddNote !== undefined && (
              <FooterAction onClick={act(onAddNote)}>
                <StickyNote aria-hidden="true" className="size-3.5" />
                {t("menuAddNote")}
              </FooterAction>
            )}
            {clipboard !== null && (
              <FooterAction
                onClick={act(() => pasteFromClipboard(useWorkflowEditorStore.getState()))}
              >
                <Clipboard aria-hidden="true" className="size-3.5" />
                {t("menuPaste")}
              </FooterAction>
            )}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

function FooterAction({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs outline-none focus-visible:ring-2"
    >
      {children}
    </button>
  );
}
