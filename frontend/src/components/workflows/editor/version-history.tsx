"use client";

import { useState } from "react";
import { GitCompare, History, RotateCcw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ListCard,
  ListCardEmpty,
  Skeleton,
  Spinner,
} from "@/components/ui";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { NodeDefinition, WorkflowVersionRead } from "@/lib/workflows/types";
import { useWorkflowVersion, useWorkflowVersions } from "@/hooks";

import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { VersionComparison } from "./version-compare";
import { VersionPreview } from "./version-preview";

/** One published version's row, with a control to open it read-only. */
function VersionRow({
  version,
  live,
  onView,
}: {
  version: WorkflowVersionRead;
  /** The version runs start from now. */
  live: boolean;
  onView: (version: WorkflowVersionRead) => void;
}) {
  const t = useTranslations("workflows");
  const format = useFormatter();

  return (
    <li className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="text-foreground flex items-center gap-2 text-sm font-medium">
          {t("versionLabel", { version: version.version })}
          {live && (
            <Badge variant="outline" className="text-muted-foreground font-normal">
              <span aria-hidden className="bg-success h-1.5 w-1.5 rounded-full" />
              {t("versionLive")}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground truncate text-xs">
          {version.note ?? t("versionNoNote")}
          {version.created_at !== null && (
            <span>
              {" · "}
              {format.dateTime(new Date(version.created_at), {
                dateStyle: "medium",
                timeZone: "UTC",
              })}
            </span>
          )}
        </p>
      </div>
      <Button variant="outline" size="sm" onClick={() => onView(version)}>
        {t("versionView")}
      </Button>
    </li>
  );
}

/**
 * The read-only preview of one selected version, with its graph fetched on demand.
 *
 * The history list is lean; the frozen graph rides only on the detail route, so
 * opening a version fetches it here (cached per version — a frozen version never
 * changes) and shows a spinner while it loads and a message if it fails.
 *
 * With `onRestore`, the preview also offers **Restore to draft**, behind a
 * confirmation: it replaces the draft, and whatever was unpublished in it is gone.
 */
function VersionPreviewDialog({
  workflowId,
  version,
  catalog,
  onRestore,
  onRestored,
}: {
  workflowId: string;
  version: WorkflowVersionRead;
  catalog: NodeDefinition[];
  onRestore?: (version: WorkflowVersionRead) => Promise<boolean>;
  onRestored: () => void;
}) {
  const t = useTranslations("workflows");
  const { version: detail, error } = useWorkflowVersion(workflowId, version.id);
  const [confirming, setConfirming] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [comparing, setComparing] = useState(false);
  const draft = useWorkflowEditorStore((state) => state.graph);

  const restore = async (restoreVersion: (version: WorkflowVersionRead) => Promise<boolean>) => {
    setRestoring(true);
    try {
      if (await restoreVersion(version)) onRestored();
    } finally {
      setRestoring(false);
      setConfirming(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("versionLabel", { version: version.version })}</DialogTitle>
        <DialogDescription>
          {onRestore === undefined ? t("versionPreviewHint") : t("versionPreviewRestoreHint")}
        </DialogDescription>
        <div>
          <Button
            variant="outline"
            size="sm"
            aria-pressed={comparing}
            disabled={detail === undefined}
            onClick={() => setComparing(!comparing)}
          >
            <GitCompare className="h-4 w-4" aria-hidden />
            {comparing ? t("versionShow") : t("versionCompare")}
          </Button>
        </div>
      </DialogHeader>
      <div className="min-h-0 flex-1">
        {error ? (
          <div className="text-muted-foreground flex h-full items-center justify-center p-6 text-sm">
            {t("versionPreviewError")}
          </div>
        ) : detail === undefined ? (
          <div className="flex h-full items-center justify-center p-6">
            <Spinner />
          </div>
        ) : comparing ? (
          <VersionComparison
            version={detail.graph}
            draft={draft ?? { ...detail.graph, nodes: [], edges: [], bindings: [], scopes: [] }}
            catalog={catalog}
          />
        ) : (
          <VersionPreview graph={detail.graph} catalog={catalog} />
        )}
      </div>
      {onRestore !== undefined && (
        <>
          <DialogFooter>
            <Button onClick={() => setConfirming(true)} disabled={restoring}>
              <RotateCcw className="h-4 w-4" aria-hidden />
              {t("versionRestore")}
            </Button>
          </DialogFooter>
          <ConfirmDialog
            open={confirming}
            onOpenChange={setConfirming}
            title={t("versionRestoreTitle", { version: version.version })}
            description={t("versionRestoreBody", { version: version.version })}
            confirmLabel={t("versionRestore")}
            loading={restoring}
            onConfirm={() => restore(onRestore)}
          />
        </>
      )}
    </>
  );
}

/**
 * The published-version history, alongside the editor.
 *
 * Each entry opens read-only: publishing froze the graph, and viewing a past
 * version draws that frozen graph in the read-only canvas posture without
 * touching the draft being edited. For a member who may edit the workflow
 * (`onRestore`), the preview can make that version the draft again; the version
 * itself never changes, and nothing is published until the draft is.
 */
export function VersionHistory({
  workflowId,
  liveVersionId,
  catalog,
  onRestore,
}: {
  workflowId: string;
  /** The version runs start from now, marked Live in the list. */
  liveVersionId: string | null;
  catalog: NodeDefinition[];
  onRestore?: (version: WorkflowVersionRead) => Promise<boolean>;
}) {
  const t = useTranslations("workflows");
  const { versions, isLoading } = useWorkflowVersions(workflowId);
  const [selected, setSelected] = useState<WorkflowVersionRead | null>(null);

  return (
    <ListCard
      title={t("versionsTitle")}
      counted={isLoading ? null : t("versionsCount", { count: versions.length })}
      contentClassName="p-0"
    >
      {isLoading ? (
        <div className="space-y-3 p-5">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : versions.length === 0 ? (
        <ListCardEmpty
          icon={History}
          title={t("versionsEmpty")}
          description={t("versionsEmptyDetail")}
        />
      ) : (
        <ul className="divide-border divide-y px-5">
          {versions.map((version) => (
            <VersionRow
              key={version.id}
              version={version}
              live={version.id === liveVersionId}
              onView={setSelected}
            />
          ))}
        </ul>
      )}

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className={cn(DIALOG_CANVAS, DIALOG_FILL)}>
          {selected !== null && (
            <VersionPreviewDialog
              workflowId={workflowId}
              version={selected}
              catalog={catalog}
              onRestore={onRestore}
              onRestored={() => setSelected(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </ListCard>
  );
}
