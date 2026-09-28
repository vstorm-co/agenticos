"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-error";
import type { WorkflowDetail, WorkflowDraftUpdate, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/**
 * How long the editor stays quiet before a draft is saved. Long enough that a
 * burst of edits — dragging a node, typing in a field — is one save, short
 * enough that a save lands before the tab is closed.
 */
export const AUTOSAVE_DEBOUNCE_MS = 400;

/** What the status indicator shows; derived from the store plus the in-flight phase. */
export type AutosaveStatus = "idle" | "pending" | "saving" | "saved" | "conflict" | "error";

/** The save phase this hook owns, before it is combined with the store's `isDirty`/`conflict`. */
type SavePhase = "idle" | "saving" | "saved" | "error";

export interface WorkflowAutosaveOptions {
  /** The draft-save call, `useWorkflow(id).saveDraft.mutateAsync`. */
  saveDraft: (update: WorkflowDraftUpdate) => Promise<WorkflowDetail>;
  /** The quiet window before a save, overridable for tests. */
  debounceMs?: number;
}

/** The server's current revision from a `409`, or null when it did not name one. */
function conflictRevision(error: ApiError): number | null {
  const value = error.details?.current_revision;
  return typeof value === "number" ? value : null;
}

/**
 * Debounced, guarded autosave for the workflow draft.
 *
 * When the working graph is dirty and no conflict stands, it waits for the edits
 * to go quiet and then PATCHes the draft with the current graph and last-known
 * `expected_revision`. The dispatch is **guarded**: a token is captured before
 * the request and re-checked when it resolves, so a save that outlives its editor
 * instance (a remount, or a same-workflow navigation away) is dropped rather than
 * landing on whatever is loaded now.
 *
 * - On success it marks the draft saved at the new revision — unless the graph
 *   changed while the request was in flight, in which case it only advances the
 *   revision and leaves the draft dirty so the newer graph saves next.
 * - A `409` raises the conflict banner (via `setConflict`) and pauses autosave
 *   until the banner is resolved.
 * - Any other failure shows an error and waits for the next edit to retry, rather
 *   than hammering a route that just refused.
 *
 * Returns the status for the save indicator.
 */
export function useWorkflowAutosave({
  saveDraft,
  debounceMs = AUTOSAVE_DEBOUNCE_MS,
}: WorkflowAutosaveOptions): AutosaveStatus {
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const conflict = useWorkflowEditorStore((state) => state.conflict);
  const expectedRevision = useWorkflowEditorStore((state) => state.expectedRevision);

  const [phase, setPhase] = useState<SavePhase>("idle");
  const savingRef = useRef(false);

  const dispatchSave = useCallback(
    async (dispatchedGraph: WorkflowGraph, expected: number) => {
      const token = useWorkflowEditorStore.getState().beginSave();
      savingRef.current = true;
      setPhase("saving");
      try {
        const detail = await saveDraft({ graph: dispatchedGraph, expected_revision: expected });
        const current = useWorkflowEditorStore.getState();
        // The save outlived its editor instance (remount / workflow switch): its
        // result belongs to a graph that is no longer loaded, so drop it.
        if (!current.isSaveCurrent(token)) return;
        if (current.getGraph() === dispatchedGraph) {
          current.markSaved(detail.draft_revision);
        } else {
          // An edit landed mid-flight; keep the draft dirty and let the newer graph
          // save against the revision this write just produced.
          current.setExpectedRevision(detail.draft_revision);
        }
        setPhase("saved");
      } catch (error) {
        if (!useWorkflowEditorStore.getState().isSaveCurrent(token)) return;
        const revision = error instanceof ApiError ? conflictRevision(error) : null;
        if (error instanceof ApiError && error.status === 409 && revision !== null) {
          useWorkflowEditorStore.getState().setConflict(revision);
        } else {
          setPhase("error");
        }
      } finally {
        savingRef.current = false;
      }
    },
    [saveDraft],
  );

  useEffect(() => {
    if (savingRef.current) return;
    if (conflict !== null) return;
    if (!isDirty) return;
    if (graph === null || expectedRevision === null) return;
    const timer = setTimeout(() => void dispatchSave(graph, expectedRevision), debounceMs);
    return () => clearTimeout(timer);
  }, [isDirty, graph, conflict, expectedRevision, debounceMs, dispatchSave]);

  if (conflict !== null) return "conflict";
  if (phase === "saving") return "saving";
  if (phase === "error") return "error";
  if (isDirty) return "pending";
  if (phase === "saved") return "saved";
  return "idle";
}
