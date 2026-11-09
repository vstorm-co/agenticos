"use client";

import type { KeyboardEvent } from "react";
import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { currentScopeId, scopedGraph } from "./scope-view";

import { copySelection, pasteClipboard } from "@/components/workflows/clipboard";
import { pasteRefusal, type PasteRefusal } from "@/components/workflows/palette";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore, type WorkflowEditorState } from "@/stores/workflow-editor-store";

/** Where a paste lands relative to its source, so it does not cover the original. */
const PASTE_OFFSET = { x: 32, y: 32 };

/** Copy the current selection into the store clipboard, if anything is selected. */
export function copyToClipboard(store: WorkflowEditorState): void {
  const graph = store.getGraph();
  if (graph === null) return;
  const clip = copySelection(graph, store.selection);
  if (clip !== null) store.setClipboard(clip);
}

const PASTE_REFUSAL_KEYS: Record<PasteRefusal, "pasteRefusedTrigger" | "pasteRefusedTooDeep"> = {
  "trigger-in-loop": "pasteRefusedTrigger",
  "too-deep": "pasteRefusedTooDeep",
};

/**
 * Paste the store clipboard back into the graph with fresh ids, if it holds one.
 *
 * Refused whole, leaving the graph and the clip as they were, when the scope being
 * viewed could not take what the clip holds - see {@link pasteRefusal}.
 */
function pasteFromClipboard(
  store: WorkflowEditorState,
  catalog: readonly NodeDefinition[],
): PasteRefusal | null {
  if (store.clipboard === null) return null;
  const refusal = pasteRefusal(store.clipboard.nodes, catalog, store.scopePath);
  if (refusal !== null) return refusal;
  const { clipboard } = pasteClipboard(
    store.clipboard,
    () => crypto.randomUUID(),
    PASTE_OFFSET,
    currentScopeId(store.scopePath),
  );
  store.insertSubgraph(clipboard);
  return null;
}

/** Paste from the store clipboard, saying why when the paste is refused. */
export function usePasteFromClipboard(catalog: readonly NodeDefinition[]): () => void {
  const t = useTranslations("workflows");
  return useCallback(() => {
    const refusal = pasteFromClipboard(useWorkflowEditorStore.getState(), catalog);
    if (refusal !== null) toast.error(t(PASTE_REFUSAL_KEYS[refusal]));
  }, [catalog, t]);
}

/** Whether a key went to a field someone is typing in, where it is text, not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.closest(
      'input, textarea, select, [contenteditable="true"], [role="textbox"], [role="dialog"], [role="menu"], [role="listbox"]',
    ) !== null
  );
}

/**
 * The canvas-scoped keyboard handler: undo/redo and copy/cut/paste wired to the
 * already-built history and clipboard modules, plus Escape to leave connect mode.
 *
 * Scoped to the canvas because it is bound to the canvas region's `onKeyDown`, so
 * it fires only while the focus is inside the editor — never stealing the
 * shortcut from an input elsewhere on the page. Every edit shortcut is inert in
 * read-only mode (a published version); Escape still cancels a stray connect.
 */
export function useCanvasShortcuts(
  readOnly: boolean,
  cancelConnect: () => void,
  catalog: readonly NodeDefinition[],
): (event: KeyboardEvent) => void {
  const paste = usePasteFromClipboard(catalog);
  return useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        cancelConnect();
        return;
      }
      // A note being written sits inside the canvas: its keys are its own.
      if (isTyping(event.target)) return;
      const store = useWorkflowEditorStore.getState();
      if (event.key === "?") {
        event.preventDefault();
        store.setOverlay("shortcuts");
        return;
      }
      if (event.key === "Tab" && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
        if (readOnly) return;
        event.preventDefault();
        store.setOverlay("picker");
        return;
      }
      if (!event.metaKey && !event.ctrlKey) return;
      if (readOnly) return;

      const key = event.key.toLowerCase();

      if (key === "a") {
        const graph = store.getGraph();
        if (graph === null) return;
        event.preventDefault();
        const visible = scopedGraph(graph, store.scopePath);
        store.setSelection({
          nodeIds: [
            ...visible.nodes.map((node) => node.id),
            ...(store.scopePath.length === 0 ? (graph.notes ?? []).map((note) => note.id) : []),
          ],
          edgeIds: visible.edges.map((edge) => edge.id),
        });
      } else if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        store.undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        store.redo();
      } else if (key === "c") {
        event.preventDefault();
        copyToClipboard(store);
      } else if (key === "x") {
        event.preventDefault();
        copyToClipboard(store);
        store.deleteSelection();
        // The cut removed the element that held focus; without a refocus the next
        // shortcut (the paste this is usually for) fires outside the canvas region.
        if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
      } else if (key === "v") {
        event.preventDefault();
        paste();
      }
    },
    [readOnly, cancelConnect, paste],
  );
}
