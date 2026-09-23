"use client";

import type { KeyboardEvent } from "react";
import { useCallback } from "react";

import { copySelection, pasteClipboard } from "@/components/workflows/clipboard";
import { useWorkflowEditorStore, type WorkflowEditorState } from "@/stores/workflow-editor-store";

/** Where a paste lands relative to its source, so it does not cover the original. */
const PASTE_OFFSET = { x: 32, y: 32 };

/** Copy the current selection into the store clipboard, if anything is selected. */
function copyToClipboard(store: WorkflowEditorState): void {
  const graph = store.getGraph();
  if (graph === null) return;
  const clip = copySelection(graph, store.selection);
  if (clip !== null) store.setClipboard(clip);
}

/** Paste the store clipboard back into the graph with fresh ids, if it holds one. */
function pasteFromClipboard(store: WorkflowEditorState): void {
  if (store.clipboard === null) return;
  const { clipboard } = pasteClipboard(store.clipboard, () => crypto.randomUUID(), PASTE_OFFSET);
  store.insertSubgraph(clipboard);
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
): (event: KeyboardEvent) => void {
  return useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        cancelConnect();
        return;
      }
      if (!event.metaKey && !event.ctrlKey) return;
      if (readOnly) return;

      const store = useWorkflowEditorStore.getState();
      const key = event.key.toLowerCase();

      if (key === "z" && !event.shiftKey) {
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
      } else if (key === "v") {
        event.preventDefault();
        pasteFromClipboard(store);
      }
    },
    [readOnly, cancelConnect],
  );
}
