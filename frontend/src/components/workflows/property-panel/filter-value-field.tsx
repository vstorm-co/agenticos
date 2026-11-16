"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useWorkflowTable } from "@/hooks";

const SELECT_TYPES = new Set(["single_select", "multi_select"]);

/**
 * A record filter's operand, chosen from the column's options when the column is
 * a single or multi select - saved as option ids, which is what every step's
 * filter matches on. Any other column, or an `is_null` test, keeps `fallback`.
 */
export function FilterValueField({
  id,
  tableId,
  columnId,
  op,
  value,
  error,
  disabled,
  fallback,
  onChange,
}: {
  id: string;
  tableId: string | null;
  columnId: unknown;
  op: unknown;
  value: unknown;
  error?: string;
  disabled?: boolean;
  fallback: ReactNode;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const { table } = useWorkflowTable(tableId);
  const column = table?.columns.find((entry) => entry.id === columnId);
  if (column === undefined || !SELECT_TYPES.has(column.type) || op === "is_null") {
    return <>{fallback}</>;
  }
  const options = column.options.filter((option) => !option.archived);

  if (op === "in") {
    const chosen = Array.isArray(value) ? value : [];
    const toggle = (optionId: string) => {
      const next = chosen.includes(optionId)
        ? chosen.filter((one) => one !== optionId)
        : [...chosen, optionId];
      onChange(next.length === 0 ? undefined : next);
    };
    return (
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium">{t("nodeFormFilterValue")}</legend>
        {options.map((option) => (
          <div key={option.id} className="flex items-center gap-2">
            <Checkbox
              id={`${id}-${option.id}`}
              checked={chosen.includes(option.id)}
              disabled={disabled}
              onCheckedChange={() => toggle(option.id)}
            />
            <Label htmlFor={`${id}-${option.id}`} className="font-normal">
              {option.label}
            </Label>
          </div>
        ))}
        {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
      </fieldset>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("nodeFormFilterValue")}</Label>
      <Select
        value={typeof value === "string" ? value : ""}
        onValueChange={onChange}
        disabled={disabled}
      >
        <SelectTrigger id={id} aria-label={t("nodeFormFilterValue")}>
          <SelectValue placeholder={t("nodeFormFilterValuePlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
