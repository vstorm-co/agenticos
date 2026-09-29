"use client";

import { useState } from "react";
import Link from "next/link";
import { History, Workflow } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Switch,
} from "@/components/ui";
import { useTableTriggerAdmissions, useTableTriggers } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, formatDateTime } from "@/lib/utils";
import type { ColumnDef, TableTriggerRead } from "@/types/tables";

/**
 * The workflows a table runs when a record is added - in the table's Triggers sheet.
 *
 * A trigger is a workflow's "New table record" node: publishing the workflow
 * switches it on, and it runs that version as the member who published it, for
 * records that match its filters as they were created - added in the console,
 * by the API, by an agent or by another workflow. A record added before it was
 * switched on never starts it. Here each can be paused and its decisions read;
 * its table and filters are changed in its workflow.
 */
export function TableTriggersPanel({
  tableId,
  columns,
  canEdit,
}: {
  tableId: string;
  columns: ColumnDef[];
  canEdit: boolean;
}) {
  const t = useTranslations("pages.tables.triggers");
  const { triggers, isLoading, setActive } = useTableTriggers(tableId);
  const [history, setHistory] = useState<TableTriggerRead | null>(null);
  const labels = new Map(columns.map((column) => [column.id, column.label]));

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("panelDescription")}</p>
      {triggers.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-sm">
          {t("empty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {triggers.map((trigger) => (
            <li
              key={trigger.id}
              className={cn("rounded-lg border p-3", !trigger.is_active && "bg-muted/30")}
            >
              <div className="flex items-start gap-3">
                <span className="bg-muted text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
                  <Workflow aria-hidden="true" className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={ROUTES.WORKFLOW_DETAIL(trigger.workflow_id)}
                    className="block truncate text-sm font-medium underline-offset-2 hover:underline"
                  >
                    {trigger.workflow_name}
                  </Link>
                  <p className="text-muted-foreground truncate text-xs">
                    {t("runs", { version: trigger.version_number })}
                  </p>
                  <p className="text-muted-foreground mt-1 text-[0.6875rem]">
                    {trigger.filters.length === 0
                      ? t("everyRecord")
                      : t("whenFiltered", {
                          columns: trigger.filters
                            .map((filter) => labels.get(filter.column_id) ?? filter.column_id)
                            .join(", "),
                        })}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {canEdit && (
                    <Switch
                      checked={trigger.is_active}
                      disabled={setActive.isPending}
                      aria-label={t("active", { name: trigger.workflow_name })}
                      onCheckedChange={(active) => setActive.mutate({ id: trigger.id, active })}
                    />
                  )}
                  {!canEdit && !trigger.is_active && <Badge variant="secondary">{t("off")}</Badge>}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("historyOf", { name: trigger.workflow_name })}
                    onClick={() => setHistory(trigger)}
                  >
                    <History className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground text-xs">{t("howToAdd")}</p>
      {history && (
        <AdmissionsDialog tableId={tableId} trigger={history} onClose={() => setHistory(null)} />
      )}
    </div>
  );
}

/** What each added record led to: a run, a filter miss, a block, a failure - never its data. */
function AdmissionsDialog({
  tableId,
  trigger,
  onClose,
}: {
  tableId: string;
  trigger: TableTriggerRead;
  onClose: () => void;
}) {
  const t = useTranslations("pages.tables.triggers");
  const locale = useLocale();
  const { admissions, isLoading } = useTableTriggerAdmissions(tableId, trigger.id);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("historyTitle", { name: trigger.workflow_name })}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={3} />
        ) : admissions.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("historyEmpty")}</p>
        ) : (
          <ul className="divide-border max-h-96 divide-y overflow-y-auto">
            {admissions.map((admission) => (
              <li key={admission.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm">{t(`status.${admission.status}`)}</p>
                  <p className="text-muted-foreground text-xs">
                    {formatDateTime(admission.created_at, locale)}
                    {admission.reason ? ` · ${t(`reason.${admission.reason}`)}` : ""}
                  </p>
                </div>
                {admission.workflow_run_id && (
                  <Link
                    href={ROUTES.WORKFLOW_RUN_DETAIL(
                      trigger.workflow_id,
                      admission.workflow_run_id,
                    )}
                    className="text-muted-foreground hover:text-foreground shrink-0 text-xs underline-offset-2 hover:underline"
                  >
                    {t("openRun")}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
