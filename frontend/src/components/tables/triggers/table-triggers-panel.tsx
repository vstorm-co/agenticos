"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpCircle, History, Pencil, Plus, Trash2, Workflow } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Switch,
} from "@/components/ui";
import { useTableTriggerAdmissions, useTableTriggers, useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, formatDateTime } from "@/lib/utils";
import type { ColumnDef, TableTriggerRead } from "@/types/tables";

import { TriggerDialog } from "./trigger-dialog";

type Editing = { trigger?: TableTriggerRead } | null;

/**
 * The workflows a table runs when a record is added - in the table's Triggers sheet.
 *
 * Each runs the version that was live when it was set up, as the member who set
 * it up, for records that match its filters as they were created, whether they
 * were added in the console, by the API, by an agent or by another workflow.
 * A record added before a trigger was switched on never starts it.
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
  const { triggers, isLoading, create, update, remove } = useTableTriggers(tableId);
  const { workflows } = useWorkflows();
  const [editing, setEditing] = useState<Editing>(null);
  const [history, setHistory] = useState<TableTriggerRead | null>(null);
  const [deleting, setDeleting] = useState<TableTriggerRead | null>(null);
  const busy = create.isPending || update.isPending || remove.isPending;
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
          {triggers.map((trigger) => {
            const workflow = workflows.find((item) => item.id === trigger.workflow_id);
            const behind =
              workflow?.current_version_id != null &&
              workflow.current_version_id !== trigger.workflow_version_id;
            return (
              <li
                key={trigger.id}
                className={cn("rounded-lg border p-3", !trigger.is_active && "bg-muted/30")}
              >
                <div className="flex items-start gap-3">
                  <span className="bg-muted text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
                    <Workflow aria-hidden="true" className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {trigger.name ?? trigger.workflow_name}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">
                      {t("runs", {
                        workflow: trigger.workflow_name,
                        version: trigger.version_number,
                      })}
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
                        disabled={busy}
                        aria-label={t("active", { name: trigger.name ?? trigger.workflow_name })}
                        onCheckedChange={(active) =>
                          update.mutate({ id: trigger.id, body: { is_active: active } })
                        }
                      />
                    )}
                    {!canEdit && !trigger.is_active && (
                      <Badge variant="secondary">{t("off")}</Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("historyOf", { name: trigger.name ?? trigger.workflow_name })}
                      onClick={() => setHistory(trigger)}
                    >
                      <History className="h-4 w-4" />
                    </Button>
                    {canEdit && (
                      <>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={t("editNamed", {
                            name: trigger.name ?? trigger.workflow_name,
                          })}
                          disabled={busy}
                          onClick={() => setEditing({ trigger })}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={t("deleteNamed", {
                            name: trigger.name ?? trigger.workflow_name,
                          })}
                          disabled={busy}
                          onClick={() => setDeleting(trigger)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                {behind && (
                  <div className="bg-muted/50 text-muted-foreground mt-2 flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                    <span>{t("behind")}</span>
                    {canEdit && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7"
                        disabled={busy}
                        onClick={() =>
                          update.mutate({ id: trigger.id, body: { pin_current_version: true } })
                        }
                      >
                        <ArrowUpCircle className="h-3.5 w-3.5" />
                        {t("repin")}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {canEdit && (
        <Button variant="outline" size="sm" onClick={() => setEditing({})}>
          <Plus className="h-4 w-4" />
          {t("new")}
        </Button>
      )}

      {editing && (
        <TriggerDialog
          columns={columns}
          workflows={workflows}
          trigger={editing.trigger}
          busy={busy}
          onOpenChange={(open) => !open && setEditing(null)}
          onSubmit={(body) => {
            const done = { onSuccess: () => setEditing(null) };
            if (editing.trigger) {
              const { workflow_id: _workflow, ...changes } = body;
              update.mutate({ id: editing.trigger.id, body: changes }, done);
            } else {
              create.mutate(body, done);
            }
          }}
        />
      )}
      {history && (
        <AdmissionsDialog tableId={tableId} trigger={history} onClose={() => setHistory(null)} />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle")}
        description={t("deleteConfirm")}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
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
          <DialogTitle>
            {t("historyTitle", { name: trigger.name ?? trigger.workflow_name })}
          </DialogTitle>
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
