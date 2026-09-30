"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { WorkflowDetail, WorkflowGraph, WorkflowVersionRead } from "@/lib/workflows/types";
import type { WorkflowRestoreInput } from "@/hooks/use-workflows";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { conflictRevision } from "./use-workflow-autosave";

/** The graph a restored draft with no graph falls back to. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/**
 * Restore a published version as the draft, without letting autosave undo it.
 *
 * Before the request, any save of the old working copy is stopped from landing:
 * the debounced one and one already in flight (`discardPendingSave`). Otherwise a
 * save queued a moment earlier could write the pre-restore graph back over the
 * restored one. On success the returned draft replaces the working copy and the
 * undo stack starts over from it.
 *
 * A `409` means the draft moved since it was read - most often a save that was
 * already on the wire. It raises the same conflict banner autosave does, and the
 * edits are put back in line to save; nothing is restored until it is resolved.
 *
 * Returns whether the restore landed.
 */
export function useRestoreVersion(
  restore: (input: WorkflowRestoreInput) => Promise<WorkflowDetail>,
): (version: WorkflowVersionRead) => Promise<boolean> {
  const t = useTranslations("workflows");
  const tErrors = useTranslations("errors");

  return useCallback(
    async (version) => {
      const store = useWorkflowEditorStore.getState();
      const expectedRevision = store.expectedRevision;
      if (expectedRevision === null) return false;
      const wasDirty = store.discardPendingSave();
      try {
        const detail = await restore({ versionId: version.id, expectedRevision });
        useWorkflowEditorStore
          .getState()
          .replaceDraft(detail.draft_graph ?? EMPTY_GRAPH, detail.draft_revision);
        toast.success(t("versionRestored", { version: version.version }));
        return true;
      } catch (error) {
        const current = useWorkflowEditorStore.getState();
        if (wasDirty) current.markDirty();
        const revision = error instanceof ApiError ? conflictRevision(error) : null;
        if (error instanceof ApiError && error.status === 409 && revision !== null) {
          current.setConflict(revision);
          toast.error(t("versionRestoreConflict"));
        } else {
          toast.error(getErrorMessage(error, tErrors));
        }
        return false;
      }
    },
    [restore, t, tErrors],
  );
}
