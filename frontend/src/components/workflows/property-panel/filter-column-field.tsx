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
import { useWorkflowTable } from "@/hooks";

/**
 * A record filter's column, chosen by name from the step's own table rather than
 * typed as an id. Only live columns are offered; until a table is chosen there is
 * nothing to choose from.
 */
export function FilterColumnField({
  id,
  tableId,
  value,
  error,
  disabled,
  onChange,
}: {
  id: string;
  tableId: string | null;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (columnId: string) => void;
}) {
  const t = useTranslations("workflows");
  const { table } = useWorkflowTable(tableId);
  const columns = table?.columns.filter((column) => !column.archived) ?? [];
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("nodeFormFilterColumn")}</Label>
      <Select
        value={typeof value === "string" ? value : ""}
        onValueChange={onChange}
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
