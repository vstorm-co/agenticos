"use client";

import { useTranslations } from "next-intl";
import { Button, Label } from "@/components/ui";
import { COMPUTED_TYPES, type ColumnInput, type CellValue } from "@/types/tables";
import { RecordCellEditor } from "./record-cell-editor";

/** Uses the same typed control as a cell. New select defaults name labels until IDs exist. */
export function ColumnDefaultField({
  id,
  column,
  onChange,
  showHint = true,
}: {
  id: string;
  column: ColumnInput;
  onChange: (value: CellValue) => void;
  showHint?: boolean;
}) {
  const t = useTranslations("tables.defaults");
  if (column.type === "rich_text" || column.type === "link" || COMPUTED_TYPES.has(column.type))
    return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={`cell-default-${id}`}>{t("value")}</Label>
        {column.default != null && (
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
            {t("clear")}
          </Button>
        )}
      </div>
      <RecordCellEditor
        column={{
          ...column,
          id: `default-${id}`,
          nullable: true,
          default: null,
          archived: false,
          options: (column.options ?? []).map((option) => ({
            ...option,
            id: option.id ?? option.label,
            archived: option.archived ?? false,
          })),
        }}
        value={column.default ?? null}
        onChange={onChange}
        placeholder={t("none")}
      />
      {showHint && <p className="text-muted-foreground text-xs">{t("hint")}</p>}
    </div>
  );
}
