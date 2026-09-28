"use client";

import type {
  NodeDefinition,
  WorkflowDetail,
  WorkflowDraftUpdate,
  WorkflowPublish,
  WorkflowVersionRead,
} from "@/lib/workflows/types";

import { AutosaveStatusIndicator } from "./autosave-status";
import { PublishDialog } from "./publish-dialog";
import { useWorkflowAutosave } from "./use-workflow-autosave";

interface EditorActionsProps {
  /** The node catalog, for the publish-time client validation. */
  catalog: NodeDefinition[];
  /** `useWorkflow(id).saveDraft.mutateAsync`, owned here by the autosave loop. */
  saveDraft: (update: WorkflowDraftUpdate) => Promise<WorkflowDetail>;
  /** `useWorkflow(id).publish.mutateAsync`. */
  publish: (input: WorkflowPublish) => Promise<WorkflowVersionRead>;
}

/**
 * The editor's header controls: the autosave status and the publish dialog.
 *
 * Mounted in the page header, it drives the debounced autosave loop (so a save
 * fires wherever the header is on screen) and reflects its status beside the
 * publish control.
 */
export function EditorActions({ catalog, saveDraft, publish }: EditorActionsProps) {
  const status = useWorkflowAutosave({ saveDraft });
  return (
    <div className="flex items-center gap-3">
      <AutosaveStatusIndicator status={status} />
      <PublishDialog catalog={catalog} publish={publish} />
    </div>
  );
}
