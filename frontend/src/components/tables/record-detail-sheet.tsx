"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  Button,
  ConfirmDialog,
  Label,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { useDeferredDelete } from "@/hooks/use-deferred-delete";
import { isRecordGone, isRevisionConflict, useRecordMutation } from "@/hooks/use-record-mutation";
import { getErrorMessage } from "@/lib/api-error";
import { useTableViewStore } from "@/stores";
import { RecordCellEditor } from "./record-cell-editor";
import type { CellValue, ColumnDef, RecordRead } from "@/types/tables";
import { recordCellText } from "@/lib/format-cell-value";
import { WorkspaceFullscreenButton } from "@/components/ui/workspace-fullscreen-button";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/utils";

import { ColumnTypeIcon } from "./column-type-icon";

/**
 * The one editing surface every view type shares: a full-row form, one
 * `RecordCellEditor` per live column. Each field commits on its own - not one
 * "Save" for the whole row - so a stale revision refuses (and is offered a
 * retry) scoped to the one field that changed, per the acceptance criterion
 * that a refused write must not lose an edit sitting beside it in the same
 * sheet.
 */
export function RecordDetailSheet({
  tableId,
  columns,
  record,
  open,
  onOpenChange,
  canEdit,
  onRecordUpdated,
}: {
  tableId: string;
  columns: ColumnDef[];
  record: RecordRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  /**
   * Called with the record as the server now holds it - after every successful
   * field commit, and after a reload - so the caller can advance its own copy
   * of `record` (typically the same state `onOpenRecord` seeded). A commit can
   * land after the sheet closed, so the caller must not treat this as "open".
   */
  onRecordUpdated: (record: RecordRead) => void;
}) {
  const t = useTranslations("tables.sheet");
  const tCells = useTranslations("tables.cells");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const boolLabel = (value: boolean) => (value ? tCells("true") : tCells("false"));
  const { commit, fetchRecord } = useRecordMutation(tableId);
  const deleteLater = useDeferredDelete(tableId);
  const [expanded, setExpanded] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const conflicts = useTableViewStore((state) => state.conflicts);
  const setConflict = useTableViewStore((state) => state.setConflict);
  const clearConflict = useTableViewStore((state) => state.clearConflict);
  // Whether the sheet is open when a write answers - it may have been closed
  // while the write was in flight.
  const openRef = useRef(open);
  useEffect(() => {
    openRef.current = open;
  }, [open]);

  /**
   * Close the sheet, committing a focused field first. Text and number fields
   * commit on blur, so blurring the focused one queues its write through the
   * same per-record chain every other commit takes - it is not lost with the
   * field when the sheet unmounts it.
   */
  const close = useCallback(() => {
    const focused = document.activeElement;
    if (focused instanceof HTMLElement) focused.blur();
    onOpenChange(false);
  }, [onOpenChange]);

  function commitField(targetRecord: RecordRead, columnId: string, value: CellValue) {
    commit(targetRecord, { [columnId]: value }).then(
      (updated) => {
        clearConflict(targetRecord.id, columnId);
        onRecordUpdated(updated);
      },
      (error: unknown) => {
        // Anything but a conflict was already toasted by `useRecordMutation`.
        if (isRevisionConflict(error)) {
          setConflict({
            recordId: targetRecord.id,
            pendingValues: { [columnId]: value },
            fieldId: columnId,
          });
          // A field committed by closing the sheet has no banner left to show
          // this; the edit waits in the store for the record to be reopened.
          if (!openRef.current) toast.error(t("conflictAfterClose"));
        }
      },
    );
  }

  /**
   * The record as the server holds it now, or `null` when reading it failed -
   * which is said, never swallowed. A record that is gone takes its pending
   * edit and the sheet with it: there is nothing left to write it to.
   */
  async function refetch(targetRecord: RecordRead, columnId: string): Promise<RecordRead | null> {
    try {
      const fresh = await fetchRecord(targetRecord.id);
      onRecordUpdated(fresh);
      return fresh;
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      if (isRecordGone(error)) {
        clearConflict(targetRecord.id, columnId);
        onOpenChange(false);
      }
      return null;
    }
  }

  /**
   * "Reload and reapply": fetch the record's current state and retry the same
   * edit against its fresh revision. The conflict is cleared only once the
   * retry write has actually landed - `commitField` does that, and re-raises
   * the banner if the retry hits another conflict. A failed refetch leaves the
   * banner (and the typed value) where it was, so the retry is still there.
   */
  async function reloadAndReapply(targetRecord: RecordRead, columnId: string, pending: CellValue) {
    const fresh = await refetch(targetRecord, columnId);
    if (fresh) commitField(fresh, columnId, pending);
  }

  /**
   * Drop the pending edit and let the field land wherever the record's
   * current server value actually places it, rather than the value this
   * sheet's `record` prop was still holding.
   */
  async function discardConflict(targetRecord: RecordRead, columnId: string) {
    clearConflict(targetRecord.id, columnId);
    await refetch(targetRecord, columnId);
  }

  /**
   * Delete the open record, with a few seconds to undo: sent against the
   * revision on screen, so a record someone changed meanwhile is kept.
   */
  function deleteRecord(targetRecord: RecordRead) {
    setConfirmingDelete(false);
    deleteLater([targetRecord]);
    onOpenChange(false);
  }

  // Named by what its first column holds - "Northwind" - the way a row is read.
  const first = columns.find((column) => !column.archived);
  const heading = record && first ? recordCellText(first, record, boolLabel, locale) : "";

  // The shared sheet owns focus and keyboard dismissal; closing still commits the focused field.
  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent
        side="right"
        className={cn("w-full", expanded ? "inset-x-0 sm:w-screen" : "sm:w-[32rem]")}
      >
        <SheetHeader>
          <SheetTitle className="truncate">{heading || t("title")}</SheetTitle>
          <div className="flex shrink-0 flex-row-reverse items-center gap-1">
            <SheetClose onClick={close} />
            <WorkspaceFullscreenButton
              expanded={expanded}
              onToggle={() => setExpanded((value) => !value)}
            />
          </div>
        </SheetHeader>
        {record && (
          <div
            className={cn(
              "min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain p-5 sm:p-6",
              expanded && "w-full sm:px-8 sm:py-6",
            )}
          >
            {columns
              .filter((column) => !column.archived)
              .map((column) => {
                // Keyed per record *and* field: two fields of the same record can
                // each be mid-write, and one landing (or one refusing) must not
                // touch the other's own pending value or banner.
                const conflict = conflicts[record.id]?.[column.id];
                const isConflicted = conflict !== undefined;
                const value = isConflicted
                  ? (conflict.pendingValues[column.id] as CellValue)
                  : (record.values[column.id] ?? null);
                return (
                  <div key={column.id} className="space-y-1">
                    <Label htmlFor={`cell-${column.id}`} className="flex items-center gap-1.5">
                      <ColumnTypeIcon type={column.type} className="text-muted-foreground" />
                      {column.label}
                    </Label>
                    <RecordCellEditor
                      column={column}
                      fillEditor={expanded && column.type === "rich_text"}
                      value={value}
                      links={record.links?.[column.id]}
                      disabled={!canEdit}
                      onChange={(next) => commitField(record, column.id, next)}
                    />
                    {isConflicted && (
                      <div className="bg-destructive/10 text-destructive space-y-1.5 rounded-md p-2 text-xs">
                        <div className="flex items-center gap-1.5">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                          <span>{t("conflict")}</span>
                        </div>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-xs"
                            onClick={() => {
                              const pending = conflict.pendingValues[column.id] as CellValue;
                              void reloadAndReapply(record, column.id, pending);
                            }}
                          >
                            {t("reloadAndReapply")}
                          </Button>
                          <Button
                            type="button"
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-xs"
                            onClick={() => void discardConflict(record, column.id)}
                          >
                            {t("discard")}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            <p className="text-muted-foreground border-border border-t pt-3 text-xs">
              {t("added", { when: formatDateTime(record.created_at, locale) })}
              {record.updated_at &&
                record.updated_at !== record.created_at &&
                ` · ${t("changed", { when: formatDateTime(record.updated_at, locale) })}`}
            </p>
          </div>
        )}
        {record && canEdit && (
          <div className="border-border mt-auto border-t px-4 py-3">
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => setConfirmingDelete(true)}
            >
              <Trash2 className="size-3.5" /> {t("delete")}
            </Button>
            <ConfirmDialog
              open={confirmingDelete}
              onOpenChange={setConfirmingDelete}
              title={t("deleteTitle")}
              description={t("deleteDescription")}
              confirmLabel={t("delete")}
              destructive
              onConfirm={() => deleteRecord(record)}
            />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
