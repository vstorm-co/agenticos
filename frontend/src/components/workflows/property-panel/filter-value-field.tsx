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
import type { OptionDef } from "@/types/tables";

const SELECT_TYPES = new Set(["single_select", "multi_select"]);

/**
 * The option a stored operand names: by id, archived or not, or by a live label
 * matched case-insensitively - List records resolves labels that way, so a step
 * may hold one. `null` when it names no option.
 */
function optionFor(options: readonly OptionDef[], value: unknown): OptionDef | null {
  if (typeof value !== "string") return null;
  const byId = options.find((option) => option.id === value);
  if (byId !== undefined) return byId;
  const wanted = value.trim().toLowerCase();
  const byLabel = options.filter(
    (option) => !option.archived && option.label.toLowerCase() === wanted,
  );
  return byLabel.length === 1 ? (byLabel[0] ?? null) : null;
}

/**
 * A record filter's operand, chosen from the column's options when the column is
 * a single or multi select - saved as option ids. A stored label shows as its
 * option, and a chosen option archived since stays listed so it can be removed.
 * Any other column, an `is_null` test, or an operand naming no option keeps
 * `fallback`, so nothing the step filters on is hidden.
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
  const many = op === "in";
  if (many && value !== undefined && !Array.isArray(value)) return <>{fallback}</>;
  const stored = many ? (Array.isArray(value) ? value : []) : value === undefined ? [] : [value];
  const chosen = stored.map((item) => optionFor(column.options, item));
  const chosenIds = chosen.flatMap((option) => (option === null ? [] : [option.id]));
  if (chosenIds.length !== stored.length) return <>{fallback}</>;
  const offered = column.options.filter(
    (option) => !option.archived || chosenIds.includes(option.id),
  );
  const labelOf = (option: OptionDef) =>
    option.archived ? t("nodeFormFilterOptionArchived", { label: option.label }) : option.label;
  const errorLine = error !== undefined && (
    <p id={`${id}-error`} className="text-destructive text-xs">
      {error}
    </p>
  );

  if (many) {
    const toggle = (optionId: string) => {
      const next = chosenIds.includes(optionId)
        ? chosenIds.filter((one) => one !== optionId)
        : [...chosenIds, optionId];
      onChange(next.length === 0 ? undefined : next);
    };
    return (
      <fieldset
        className="space-y-1.5"
        aria-invalid={error !== undefined}
        aria-describedby={error === undefined ? undefined : `${id}-error`}
      >
        <legend className="text-sm font-medium">{t("nodeFormFilterValue")}</legend>
        {offered.map((option) => (
          <div key={option.id} className="flex items-center gap-2">
            <Checkbox
              id={`${id}-${option.id}`}
              checked={chosenIds.includes(option.id)}
              disabled={disabled}
              onCheckedChange={() => toggle(option.id)}
            />
            <Label htmlFor={`${id}-${option.id}`} className="font-normal">
              {labelOf(option)}
            </Label>
          </div>
        ))}
        {errorLine}
      </fieldset>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("nodeFormFilterValue")}</Label>
      <Select value={chosenIds[0] ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger
          id={id}
          aria-invalid={error !== undefined}
          aria-describedby={error === undefined ? undefined : `${id}-error`}
        >
          <SelectValue placeholder={t("nodeFormFilterValuePlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {offered.map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {labelOf(option)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {errorLine}
    </div>
  );
}
