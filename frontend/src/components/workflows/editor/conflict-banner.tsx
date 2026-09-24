"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { qk } from "@/lib/query-keys";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { getWorkflow } from "@/lib/workflows/workflows-api";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** The graph a reloaded workflow with no draft falls back to. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/**
 * The revision-conflict banner.
 *
 * Shown when an autosave (or a publish) hits a `409`: the draft was changed
 * somewhere else since it was last read. Two ways out, exactly as #1781's lab
 * proved:
 *
 * - **Overwrite** — keep the local edits and resend them against the revision the
 *   server says is current. It advances `expected_revision` and clears the
 *   conflict; the autosave loop then saves the local graph against it.
 * - **Reload** — discard the local edits, refetch the draft and reseed the canvas
 *   with the server's copy.
 *
 * Nothing renders when there is no conflict.
 */
export function ConflictBanner({ workflowId }: { workflowId: string }) {
  const t = useTranslations("workflows");
  const queryClient = useQueryClient();
  const conflict = useWorkflowEditorStore((state) => state.conflict);
  const setExpectedRevision = useWorkflowEditorStore((state) => state.setExpectedRevision);
  const clearConflict = useWorkflowEditorStore((state) => state.clearConflict);
  const seedGraph = useWorkflowEditorStore((state) => state.seedGraph);
  const markSaved = useWorkflowEditorStore((state) => state.markSaved);

  const [reloading, setReloading] = useState(false);

  const overwrite = useCallback(
    (currentRevision: number) => {
      setExpectedRevision(currentRevision);
      clearConflict();
    },
    [setExpectedRevision, clearConflict],
  );

  const reload = useCallback(async () => {
    setReloading(true);
    try {
      const detail = await queryClient.fetchQuery({
        queryKey: qk.workflows.detail(workflowId),
        queryFn: () => getWorkflow(workflowId),
      });
      seedGraph(detail.draft_graph ?? EMPTY_GRAPH);
      markSaved(detail.draft_revision);
    } finally {
      setReloading(false);
    }
  }, [queryClient, workflowId, seedGraph, markSaved]);

  if (conflict === null) return null;

  return (
    <div
      role="alert"
      data-workflow-conflict
      className="flex flex-col gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
        <div>
          <p className="text-foreground text-sm font-medium">{t("conflictTitle")}</p>
          <p className="text-muted-foreground text-sm">{t("conflictBody")}</p>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => overwrite(conflict.currentRevision)}
          disabled={reloading}
        >
          {t("conflictOverwrite")}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void reload()} disabled={reloading}>
          {t("conflictReload")}
        </Button>
      </div>
    </div>
  );
}
