"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui";
import { useRecordMutation } from "@/hooks/use-record-mutation";
import type { CellValue, ColumnDef } from "@/types/tables";

import { isRequired } from "./new-record-dialog";

/** The column a new line types into: the first one that holds a line of text. */
function firstTextColumn(columns: ColumnDef[]): ColumnDef | null {
  return columns.find((column) => column.type === "text" && !column.archived) ?? null;
}

/**
 * The line under the grid where a record is typed in: what is typed goes into
 * the first text column, and Enter creates the record - the next one can be
 * typed straight away. A table that needs more than that line holds - another
 * required column - opens the Add record form with it filled in instead, so a
 * required value is asked for before the record exists, never refused after.
 */
export function NewRecordRow({
  tableId,
  columns,
  onNeedsMore,
}: {
  tableId: string;
  /** The table's live columns, in the view's order. */
  columns: ColumnDef[];
  /** Open the full form, starting from what was typed. */
  onNeedsMore: (values: Record<string, CellValue>) => void;
}) {
  const t = useTranslations("tables.grid");
  const { create } = useRecordMutation(tableId);
  const [text, setText] = useState("");
  const target = firstTextColumn(columns);

  if (target === null) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="text-muted-foreground mt-1"
        onClick={() => onNeedsMore({})}
      >
        <Plus className="size-3.5" />
        {t("newRecord")}
      </Button>
    );
  }

  const submit = async () => {
    const value = text.trim();
    if (value === "") return;
    const values = { [target.id]: value };
    const others = columns.filter(
      (column) => column.id !== target.id && !column.archived && isRequired(column),
    );
    if (others.length > 0) {
      onNeedsMore(values);
      setText("");
      return;
    }
    try {
      await create.mutateAsync({ values });
      setText("");
      // The table may be long and sorted away from where the record lands.
      toast.success(t("newRecordAdded", { value }));
    } catch {
      // The hook already said what went wrong; the line keeps what was typed.
    }
  };

  return (
    <div className="border-border mt-1 flex items-center gap-2 rounded-lg border border-dashed px-3">
      <Plus aria-hidden className="text-muted-foreground size-3.5 shrink-0" />
      <Input
        aria-label={t("newRecordLine", { column: target.label })}
        placeholder={t("newRecordPlaceholder", { column: target.label })}
        value={text}
        disabled={create.isPending}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void submit();
          }
          if (event.key === "Escape") setText("");
        }}
        className="h-11 border-0 px-0 shadow-none focus-visible:ring-0"
      />
    </div>
  );
}
