"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import { Button, Label, Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui";
import { isRevisionConflict, useRecordMutation } from "@/hooks/use-record-mutation";
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
  onRefetchRecord,
  onRecordUpdated,
}: {
  tableId: string;
  columns: ColumnDef[];
  record: RecordRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  /**
   * Refreshes and returns the current record from the server. "Reload and
   * reapply" awaits this and writes against *its* revision rather than the
   * `record` prop, which a React re-render has not necessarily replaced by the
   * time the awaited call returns - a stale-closure retry would fail the same
   * conflict a second time.
   */
  onRefetchRecord: () => Promise<RecordRead | undefined>;
  /**
   * Called with the server's response after every successful field commit, so
   * the caller can advance its own copy of `record` (typically the same state
   * `onOpenRecord` seeded). Without this, a second field edit - or a second
   * edit to the same field - keeps submitting the revision this sheet opened
   * with, and 409s every time after the first successful write.
   */
  onRecordUpdated: (record: RecordRead) => void;
}) {
  const t = useTranslations("tables.sheet");
  const { update } = useRecordMutation(tableId);
  const conflicts = useTableViewStore((state) => state.conflicts);
  const setConflict = useTableViewStore((state) => state.setConflict);
  const clearConflict = useTableViewStore((state) => state.clearConflict);

  function commitField(targetRecord: RecordRead, columnId: string, value: CellValue) {
    update.mutate(
      {
        recordId: targetRecord.id,
        data: { expected_revision: targetRecord.revision, values: { [columnId]: value } },
      },
      {
        onSuccess: (updated) => {
          clearConflict(targetRecord.id);
          onRecordUpdated(updated);
        },
        onError: (error) => {
          if (isRevisionConflict(error)) {
            setConflict({
              recordId: targetRecord.id,
              pendingValues: { [columnId]: value },
              fieldId: columnId,
            });
          }
        },
      },
    );
  }

  /**
   * "Reload and reapply": fetch the record's current state and retry the same
   * edit against its fresh revision. The conflict is cleared only once the
   * refetch has actually landed - clearing it first would drop the pending
   * edit for good the moment the refetch itself fails (a network error, the
   * record having been deleted meanwhile), with no way back to it. A failed
   * refetch leaves the banner exactly as it was, so the retry is still there.
   */
  async function reloadAndReapply(targetRecord: RecordRead, columnId: string, pending: CellValue) {
    try {
      const fresh = await onRefetchRecord();
      clearConflict(targetRecord.id);
      if (fresh) commitField(fresh, columnId, pending);
    } catch {
      // The refetch failed - the conflict (and the typed value) stays put.
    }
  }

  /**
   * Drop the pending edit and let the field land wherever the record's
   * current server value actually places it, rather than the value this
   * sheet's `record` prop was still holding. `onRefetchRecord` updates the
   * caller's own record state as one of its documented effects.
   */
  async function discardConflict(targetRecord: RecordRead) {
    clearConflict(targetRecord.id);
    try {
      await onRefetchRecord();
    } catch {
      // Already discarded locally; a failed refetch leaves the sheet showing
      // the record as it was last known, which is no worse than before.
    }
  }

  const conflict = record ? conflicts[record.id] : undefined;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{t("title")}</SheetTitle>
        </SheetHeader>
        {record && (
          <div className="space-y-4 overflow-y-auto px-1 py-2">
            {columns
              .filter((column) => !column.archived)
              .map((column) => {
                const isConflicted = conflict?.fieldId === column.id;
                // `conflict` is defined whenever `isConflicted` is true - that is
                // exactly what `conflict?.fieldId === column.id` being true means -
                // and `setConflict` always writes `pendingValues[conflict.fieldId]`,
                // so the pending value for this column is always present too.
                const value = isConflicted
                  ? (conflict!.pendingValues[column.id] as CellValue)
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
                              const pending = conflict?.pendingValues[column.id] as CellValue;
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
                            onClick={() => void discardConflict(record)}
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
