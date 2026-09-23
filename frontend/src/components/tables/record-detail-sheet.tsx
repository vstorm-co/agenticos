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
        onSuccess: () => clearConflict(targetRecord.id),
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
                            onClick={async () => {
                              const pending = conflict?.pendingValues[column.id] as CellValue;
                              clearConflict(record.id);
                              const fresh = await onRefetchRecord();
                              if (fresh) commitField(fresh, column.id, pending);
                            }}
                          >
                            {t("reloadAndReapply")}
                          </Button>
                          <Button
                            type="button"
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-xs"
                            onClick={() => clearConflict(record.id)}
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
