"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import {
  Button,
  Label,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { isRecordGone, isRevisionConflict, useRecordMutation } from "@/hooks/use-record-mutation";
import { getErrorMessage } from "@/lib/api-error";
import { useTableViewStore } from "@/stores";
import { RecordCellEditor } from "./record-cell-editor";
import type { CellValue, ColumnDef, RecordRead } from "@/types/tables";

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
  const tErrors = useTranslations("errors");
  const { commit, fetchRecord } = useRecordMutation(tableId);
  const conflicts = useTableViewStore((state) => state.conflicts);
  const setConflict = useTableViewStore((state) => state.setConflict);
  const clearConflict = useTableViewStore((state) => state.clearConflict);
  const closeRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    // Focus enters the sheet, so a keyboard user can reach its fields at all.
    if (open) closeRef.current?.querySelector("button")?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      // A select or popover inside the sheet closes itself on Escape and marks
      // the event handled; that Escape is its own, not the sheet's.
      if (event.key === "Escape" && !event.defaultPrevented) close();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

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

  // `Sheet` calls `onOpenChange` only from an overlay click, always to close.
  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{t("title")}</SheetTitle>
          <div ref={closeRef}>
            <SheetClose onClick={close} />
          </div>
        </SheetHeader>
        {record && (
          <div className="space-y-4 overflow-y-auto px-1 py-2">
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
                    <Label htmlFor={`cell-${column.id}`}>{column.label}</Label>
                    <RecordCellEditor
                      column={column}
                      value={value}
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
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
