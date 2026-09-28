"use client";

import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useWorkflowTable, useWorkflowTables } from "@/hooks";
import type { ColumnDef, TableSummary } from "@/lib/workflows/tables-api";
import type { TableIORef } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

export interface TableColumnPickerProps {
  value: TableIORef | null;
  onChange: (next: TableIORef | null) => void;
  disabled?: boolean;
  /** A validation message from the property panel, shown under the control. */
  error?: string;
}

/** A fresh ref pinned to a table's current schema, all columns. */
function refForTable(table: TableSummary): TableIORef {
  return {
    kind: "table",
    table_id: table.id,
    column_ids: null,
    schema_version: table.schema_version,
  };
}

/** A checkbox row, the shape `collection-picker` uses to disambiguate by content. */
function ColumnRow({
  label,
  type,
  checked,
  disabled,
  onToggle,
}: {
  label: string;
  type?: string;
  checked: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex w-full items-center gap-2 rounded-lg border p-2 text-left text-sm",
        checked ? "border-brand bg-brand/5" : "hover:border-foreground/20",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <span
        className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
          checked ? "border-brand bg-brand text-brand-foreground" : "border-input",
        )}
      >
        {checked && <Check className="h-3 w-3" />}
      </span>
      <span className="truncate">{label}</span>
      {type !== undefined && (
        <span className="text-muted-foreground ml-auto font-mono text-xs">{type}</span>
      )}
    </button>
  );
}

/**
 * The columns of a table whose schema still matches the ref, as toggles.
 *
 * `column_ids: null` is "every live column" - so ticking every column collapses
 * back to null rather than freezing the current set, and an unnarrowed ref keeps
 * following the schema. Narrowing to a subset writes the explicit list.
 */
function ColumnSelector({
  value,
  columns,
  onChange,
  disabled,
}: {
  value: TableIORef;
  columns: ColumnDef[];
  onChange: (next: TableIORef) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("workflows");
  const allSelected = value.column_ids === null;
  const isSelected = (id: string) => value.column_ids === null || value.column_ids.includes(id);

  function select(nextIds: string[]) {
    const everyLive =
      nextIds.length === columns.length && columns.every((c) => nextIds.includes(c.id));
    onChange({ ...value, column_ids: everyLive ? null : nextIds });
  }

  function toggle(column: ColumnDef) {
    const current = value.column_ids ?? columns.map((c) => c.id);
    select(
      current.includes(column.id)
        ? current.filter((id) => id !== column.id)
        : [...current, column.id],
    );
  }

  return (
    <div className="space-y-1.5">
      <ColumnRow
        label={t("pickerColumnsAll")}
        checked={allSelected}
        disabled={disabled}
        onToggle={() => onChange({ ...value, column_ids: null })}
      />
      {columns.map((column) => (
        <ColumnRow
          key={column.id}
          label={column.label}
          type={column.type}
          checked={isSelected(column.id)}
          disabled={disabled}
          onToggle={() => toggle(column)}
        />
      ))}
    </div>
  );
}

/**
 * Which virtual table a node reads or writes, narrowed to which columns.
 *
 * Two steps against a `TableIORef`. The column list is scoped to the table's
 * *current* schema (`GET /tables/{id}`), never the schema the ref was bound
 * against: a column added since is offered, and one archived since is gone.
 *
 * A ref whose `schema_version` no longer matches the table's gets the orphaned
 * treatment - a field-scoped banner and no live column toggles - because its
 * `column_ids` name a version's columns that may no longer exist. #1784
 * revalidates at execution time regardless; rebinding here only spares the author
 * a publish-time refusal.
 */
export function TableColumnPicker({ value, onChange, disabled, error }: TableColumnPickerProps) {
  const t = useTranslations("workflows");
  const { tables, isLoading: tablesLoading } = useWorkflowTables();
  const { table, isLoading: tableLoading } = useWorkflowTable(value?.table_id ?? null);

  const chosen = tables.find((entry) => entry.id === value?.table_id);
  const tableOrphaned = value !== null && !tablesLoading && chosen === undefined;
  const schemaChanged =
    value !== null && table !== null && table.schema_version !== value.schema_version;
  const liveColumns = table?.columns.filter((column) => !column.archived) ?? [];

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>{t("pickerTableLabel")}</Label>
        <Select
          value={value?.table_id ?? ""}
          onValueChange={(tableId) => {
            const picked = tables.find((entry) => entry.id === tableId);
            if (picked) onChange(refForTable(picked));
          }}
          disabled={disabled}
        >
          <SelectTrigger aria-label={t("pickerTableLabel")}>
            <SelectValue placeholder={t("pickerTablePlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {tables.map((entry) => (
              <SelectItem key={entry.id} value={entry.id}>
                {entry.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {tables.length === 0 && !tablesLoading && (
          <p className="text-muted-foreground text-xs">{t("pickerTablesEmpty")}</p>
        )}
        {tableOrphaned && (
          <p className="text-foreground/70 flex items-center gap-1.5 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {t("pickerTableOrphaned")} <span className="font-mono break-all">{value.table_id}</span>
          </p>
        )}
      </div>

      {value !== null && !tableOrphaned && (
        <div className="space-y-2">
          <Label>{t("pickerColumnsLabel")}</Label>
          {tableLoading && (
            <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("pickerColumnsLoading")}
            </p>
          )}
          {schemaChanged && (
            <div className="border-border rounded-lg border border-dashed p-3">
              <p className="text-foreground/80 flex items-center gap-1.5 text-xs">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                {t("pickerSchemaChanged")}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2"
                disabled={disabled}
                onClick={() => table && onChange(refForTable(table))}
              >
                {t("pickerRebind")}
              </Button>
            </div>
          )}
          {table !== null && !schemaChanged && (
            <ColumnSelector
              value={value}
              columns={liveColumns}
              onChange={onChange}
              disabled={disabled}
            />
          )}
        </div>
      )}

      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
