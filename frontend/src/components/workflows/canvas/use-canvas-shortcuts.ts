"use client";

import type { KeyboardEvent } from "react";
import { useCallback } from "react";

import { copySelection, pasteClipboard } from "@/components/workflows/clipboard";
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

/** Paste the store clipboard back into the graph with fresh ids, if it holds one. */
export function pasteFromClipboard(store: WorkflowEditorState): void {
  if (store.clipboard === null) return;
  const { clipboard } = pasteClipboard(store.clipboard, () => crypto.randomUUID(), PASTE_OFFSET);
  store.insertSubgraph(clipboard);
}

/** Whether a key went to a field someone is typing in, where it is text, not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
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
        // The cut removed the element that held focus; without a refocus the next
        // shortcut (the paste this is usually for) fires outside the canvas region.
        if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
      } else if (key === "v") {
        event.preventDefault();
        pasteFromClipboard(store);
      }
    },
    [readOnly, cancelConnect],
  );
}
