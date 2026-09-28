"use client";

import { useState } from "react";
import { History } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
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

import { VersionPreview } from "./version-preview";

/** One published version's row, with a control to open it read-only. */
function VersionRow({
  version,
  onView,
}: {
  version: WorkflowVersionRead;
  onView: (version: WorkflowVersionRead) => void;
}) {
  const t = useTranslations("workflows");
  const format = useFormatter();

  return (
    <li className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="text-foreground text-sm font-medium">
          {t("versionLabel", { version: version.version })}
        </p>
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
 */
function VersionPreviewDialog({
  workflowId,
  version,
  catalog,
}: {
  workflowId: string;
  version: WorkflowVersionRead;
  catalog: NodeDefinition[];
}) {
  const t = useTranslations("workflows");
  const { version: detail, error } = useWorkflowVersion(workflowId, version.id);

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("versionLabel", { version: version.version })}</DialogTitle>
        <DialogDescription>{t("versionPreviewHint")}</DialogDescription>
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
        ) : (
          <VersionPreview graph={detail.graph} catalog={catalog} />
        )}
      </div>
    </>
  );
}

/**
 * The published-version history, alongside the editor.
 *
 * Each entry opens read-only: publishing froze the graph, and viewing a past
 * version draws that frozen graph in the read-only canvas posture without
 * touching the draft being edited. Editing a workflow after publishing is just
 * continuing to edit the draft, so there is no "restore" mode — the draft always
 * exists independently of any version.
 */
export function VersionHistory({
  workflowId,
  catalog,
}: {
  workflowId: string;
  catalog: NodeDefinition[];
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
            <VersionRow key={version.id} version={version} onView={setSelected} />
          ))}
        </ul>
      )}

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className={cn(DIALOG_CANVAS, DIALOG_FILL)}>
          {selected !== null && (
            <VersionPreviewDialog workflowId={workflowId} version={selected} catalog={catalog} />
          )}
        </DialogContent>
      </Dialog>
    </ListCard>
  );
}
