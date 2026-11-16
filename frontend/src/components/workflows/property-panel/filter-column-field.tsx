"use client";

import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { filterable } from "@/components/tables/record-filters";
import { useWorkflowTable } from "@/hooks";
import type { ColumnDef } from "@/types/tables";

/**
 * A record filter's column, chosen by name from the step's own table rather than
 * typed as an id. Only live columns a filter can test are offered; until a table
 * is chosen there is nothing to choose from. `onPick` hands back the whole column,
 * so the caller can start the row afresh for it.
 */
export function FilterColumnField({
  id,
  tableId,
  value,
  error,
  disabled,
  onPick,
}: {
  id: string;
  tableId: string | null;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onPick: (column: ColumnDef) => void;
}) {
  const t = useTranslations("workflows");
  const { table } = useWorkflowTable(tableId);
  const columns = table?.columns.filter((column) => !column.archived && filterable(column)) ?? [];
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("nodeFormFilterColumn")}</Label>
      <Select
        value={typeof value === "string" ? value : ""}
        // Every item's value is one of `columns`, so the lookup always finds it.
        onValueChange={(columnId) =>
          onPick(columns.find((column) => column.id === columnId) as ColumnDef)
        }
        disabled={disabled || tableId === null || table === null}
      >
        <SelectTrigger id={id} aria-label={t("nodeFormFilterColumn")}>
          <SelectValue
            placeholder={
              tableId === null
                ? t("nodeFormFilterColumnNoTable")
                : t("nodeFormFilterColumnPlaceholder")
            }
          />
        </SelectTrigger>
        <SelectContent>
          {columns.map((column) => (
            <SelectItem key={column.id} value={column.id}>
              {column.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
