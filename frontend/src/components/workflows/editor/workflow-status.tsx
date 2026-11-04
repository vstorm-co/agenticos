"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { useWorkflowVersion } from "@/hooks";
import { diffGraphs } from "@/lib/workflows/graph-diff";
import type { WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

/**
 * The live version's number, and whether the draft differs from it the way a
 * publish would carry - moving a step or pinning test data is not such a change
 * (`diffGraphs`). `live` is null for a workflow never published, and while the
 * live version is being read; `changed` is false until it has been.
 */
export function useLiveChanges(
  workflow: WorkflowDetail,
  draft: WorkflowGraph | null,
): { live: number | null; changed: boolean } {
  const { version } = useWorkflowVersion(workflow.id, workflow.current_version_id);
  if (workflow.current_version_id === null || version === undefined) {
    return { live: null, changed: false };
  }
  const diff = draft === null ? null : diffGraphs(version.graph, draft);
  const changed =
    diff !== null && (diff.steps.size > 0 || diff.edgesAdded > 0 || diff.edgesRemoved > 0);
  return { live: version.version, changed };
}

/**
 * Where a workflow stands, as the editor's header says it: a draft never
 * published, the live version by its number, and that the draft has changes
 * still to publish (`useLiveChanges`). Archived says so and nothing else.
 */
export function WorkflowStatus({
  workflow,
  draft,
}: {
  workflow: WorkflowDetail;
  /** The draft as the editor holds it now, edits not yet saved included. */
  draft: WorkflowGraph | null;
}) {
  const t = useTranslations("pages.workflows");
  const { live, changed } = useLiveChanges(workflow, draft);

  if (workflow.status === "archived") {
    return <Dot tone="bg-muted-foreground/50" label={t("statusArchived")} />;
  }
  if (workflow.current_version_id === null) {
    return <Dot tone="bg-warning" label={t("statusNeverPublished")} />;
  }
  if (live === null) return <Dot tone="bg-success" label={t("statusLive")} />;
  return (
    <div className="inline-flex items-center gap-2">
      <Dot tone="bg-success" label={t("statusLiveVersion", { version: live })} />
      {changed && (
        <span className="text-muted-foreground text-xs">{t("statusUnpublishedChanges")}</span>
      )}
    </div>
  );
}

function Dot({ tone, label }: { tone: string; label: string }) {
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone)} />
      {label}
    </Badge>
  );
}
