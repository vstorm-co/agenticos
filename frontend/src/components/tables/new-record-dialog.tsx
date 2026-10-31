"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
} from "@/components/ui";
import { useRecordMutation } from "@/hooks/use-record-mutation";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { COMPUTED_TYPES, type CellValue, type ColumnDef } from "@/types/tables";

import { RecordCellEditor } from "./record-cell-editor";
import { toastDone } from "@/lib/toast";

interface NewRecordDialogProps {
  tableId: string;
  /** The table's live columns - an archived one takes no value. */
  columns: ColumnDef[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What the form starts with - a value typed on the grid's new-record line. */
  initial?: Record<string, CellValue>;
}

/** Whether a column needs a value from whoever adds a record: not nullable, and no default. */
export function isRequired(column: ColumnDef): boolean {
  return !column.nullable && column.default === null;
}

/**
 * What the form starts with: a yes/no that cannot be empty starts at no - a
 * switch has no "not set" to show - and every other field starts empty.
 */
function seed(columns: ColumnDef[]): Record<string, CellValue> {
  return Object.fromEntries(
    columns
      .filter((column) => column.type === "boolean" && isRequired(column))
      .map((column) => [column.id, false]),
  );
}

function isEmpty(value: CellValue | undefined): boolean {
  return (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

/**
 * Add one record from the console: a field per live column, typed as the column
 * is, created in one write.
 *
 * A required column - not nullable and with no default - is asked for before
 * the write, so the service's refusal is the exception rather than the way the
 * builder learns what the table needs. A column left empty takes its default.
 * The record is made by the member, like any other write: its history says so,
 * and a table trigger fires for it.
 */
export function NewRecordDialog({
  tableId,
  columns,
  open,
  onOpenChange,
  initial,
}: NewRecordDialogProps) {
  const t = useTranslations("pages.tables.newRecord");
  const { create } = useRecordMutation(tableId);
  // A worked-out column has nothing to fill in: it reads its link once one is made.
  const live = columns.filter((column) => !column.archived && !COMPUTED_TYPES.has(column.type));
  const [values, setValues] = useState<Record<string, CellValue>>(() => ({
    ...seed(live),
    ...initial,
  }));
  const [tried, setTried] = useState(false);

  const missing = live.filter((column) => isRequired(column) && isEmpty(values[column.id]));

  const close = (next: boolean) => {
    if (!next) {
      setValues(seed(live));
      setTried(false);
    }
    onOpenChange(next);
  };

  const submit = async () => {
    setTried(true);
    if (missing.length > 0) return;
    const filled = Object.fromEntries(
      Object.entries(values).filter(([, value]) => !isEmpty(value)),
    );
    try {
      await create.mutateAsync({ values: filled });
      toastDone(t("created"));
      close(false);
    } catch {
      // The hook already said what went wrong; the form keeps what was typed.
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={`${DIALOG_COLUMN} ${DIALOG_FORM}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} grid grid-cols-1 gap-5 sm:grid-cols-2`}>
          {live.map((column) => {
            const needed = isRequired(column);
            return (
              <div
                key={column.id}
                className={
                  column.type === "long_text" ||
                  column.type === "link" ||
                  column.type === "multi_select"
                    ? "space-y-1.5 sm:col-span-2"
                    : "space-y-1.5"
                }
              >
                <Label htmlFor={`cell-${column.id}`}>
                  {column.label}
                  {needed && <span className="text-muted-foreground"> *</span>}
                </Label>
                <RecordCellEditor
                  column={column}
                  value={values[column.id] ?? null}
                  onChange={(value) => setValues({ ...values, [column.id]: value })}
                  disabled={create.isPending}
                  error={tried && needed && isEmpty(values[column.id]) ? t("required") : undefined}
                />
              </div>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={create.isPending}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
