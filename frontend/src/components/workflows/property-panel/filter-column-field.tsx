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
  const savedId = typeof value === "string" && value !== "" ? value : null;
  const unavailable = savedId !== null && !columns.some((column) => column.id === savedId);
  const savedColumn = table?.columns.find((column) => column.id === savedId);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("nodeFormFilterColumn")}</Label>
      <Select
        value={typeof value === "string" ? value : ""}
        onValueChange={(columnId) => {
          const column = columns.find((entry) => entry.id === columnId);
          if (column !== undefined) onPick(column);
        }}
        disabled={disabled || tableId === null || table === null}
      >
        <SelectTrigger
          id={id}
          aria-invalid={error !== undefined}
          aria-describedby={error === undefined ? undefined : `${id}-error`}
        >
          <SelectValue
            placeholder={
              tableId === null
                ? t("nodeFormFilterColumnNoTable")
                : t("nodeFormFilterColumnPlaceholder")
            }
          />
        </SelectTrigger>
        <SelectContent>
          {unavailable && (
            <SelectItem value={savedId} disabled>
              {savedColumn?.label ?? savedId}
            </SelectItem>
          )}
          {columns.map((column) => (
            <SelectItem key={column.id} value={column.id}>
              {column.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error !== undefined && (
        <p id={`${id}-error`} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
