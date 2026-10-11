"use client";

import { AlertTriangle, Check, CloudOff, Loader2, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import type { WorkflowDetail, WorkflowDraftUpdate } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

import { type AutosaveStatus, useWorkflowAutosave } from "./use-workflow-autosave";

/** Icon, copy key and tone for each status. `idle` renders nothing. */
const PRESENTATION: Record<
  Exclude<AutosaveStatus, "idle">,
  { icon: typeof Check; labelKey: string; tone: string; spin?: boolean }
> = {
  pending: { icon: Pencil, labelKey: "autosavePending", tone: "text-muted-foreground" },
  saving: { icon: Loader2, labelKey: "autosaveSaving", tone: "text-muted-foreground", spin: true },
  saved: { icon: Check, labelKey: "autosaveSaved", tone: "text-muted-foreground" },
  conflict: { icon: CloudOff, labelKey: "autosaveConflict", tone: "text-amber-600" },
  error: { icon: AlertTriangle, labelKey: "autosaveError", tone: "text-destructive" },
};

/**
 * The save-state indicator, under the workflow's title.
 *
 * Presentational: it reflects the status the autosave hook computes. Nothing
 * renders in the `idle` state — a workflow just opened has nothing to say about a
 * save that has not happened. The text is an `aria-live` region so a screen reader
 * hears "Saving…" then "Saved" without moving focus.
 */
export function AutosaveStatusIndicator({ status }: { status: AutosaveStatus }) {
  const t = useTranslations("workflows");
  const presentation = status === "idle" ? null : PRESENTATION[status];

  return (
    <span
      role="status"
      aria-live="polite"
      data-autosave-status={status}
      className="flex items-center gap-1.5 text-xs"
    >
      {presentation && (
        <>
          <presentation.icon
            className={cn("h-3.5 w-3.5", presentation.tone, presentation.spin && "animate-spin")}
            aria-hidden
          />
          <span className={presentation.tone}>{t(presentation.labelKey)}</span>
        </>
      )}
    </span>
  );
}

/**
 * The draft's autosave loop, shown where it says how the save went: at the end
 * of the row under the title, where a status that changes length moves nothing
 * else - beside the header's buttons it pushed them along on every edit.
 */
export function DraftAutosave({
  saveDraft,
}: {
  /** `useWorkflow(id).saveDraft.mutateAsync`, owned here by the autosave loop. */
  saveDraft: (update: WorkflowDraftUpdate) => Promise<WorkflowDetail>;
}) {
  return <AutosaveStatusIndicator status={useWorkflowAutosave({ saveDraft })} />;
}
