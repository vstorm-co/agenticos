"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_COLUMN } from "@/lib/dialog-sizes";
import { fieldProblems } from "@/lib/api-error";
import type { ColumnInput, ColumnTypeName, TableRead } from "@/types/tables";

const COLUMN_TYPES: ColumnTypeName[] = [
  "text",
  "long_text",
  "number",
  "integer",
  "boolean",
  "date",
  "datetime",
  "single_select",
  "multi_select",
];

interface Row extends ColumnInput {
  /** A stable React key independent of the backend id - a new column has none yet. */
  key: string;
}

function toRows(table: TableRead): Row[] {
  return table.columns.map((column) => ({
    key: column.id,
    id: column.id,
    label: column.label,
    type: column.type,
    nullable: column.nullable,
    default: column.default,
    options: column.options.map((option) => ({
      id: option.id,
      label: option.label,
      archived: option.archived,
    })),
    archived: column.archived,
  }));
}

function blankRow(): Row {
  return { key: crypto.randomUUID(), label: "", type: "text", nullable: true, options: [] };
}

/**
 * Add, rename, retype (new columns only), archive/restore and reorder-free
 * edit of a table's columns, submitted as one `SchemaUpdate`.
 *
 * Mirrors what the service actually enforces rather than re-deriving it: a
 * column with an `id` keeps it and cannot change `type`; a column removed from
 * the submission is archived, never deleted, and the same is true of an option
 * left off a `single_select`/`multi_select` column's list. Both directions
 * hold - `archived: false` on a row already archived on the server is a
 * request to bring it back - and the fields the server refuses (an unfillable
 * required column, a broken default, a taken label) come back as
 * `columns.<n>.<field>` and are shown beside that row.
 */
export function SchemaEditorDialog({
  open,
  onOpenChange,
  table,
  onSave,
  isSaving,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  table: TableRead;
  onSave: (columns: ColumnInput[]) => void;
  isSaving: boolean;
  error: unknown;
}) {
  const t = useTranslations("tables.schema");
  const [rows, setRows] = useState<Row[]>(() => toRows(table));
  // Re-seeded from the table each time the dialog opens on a schema version it
  // has not shown yet - adjusted during render (React's own pattern for this,
  // https://react.dev/learn/you-might-not-need-an-effect) rather than in a
  // `useEffect`, which would paint the previous open's rows for one frame
  // before the effect ran.
  const [seededAt, setSeededAt] = useState<string | null>(null);
  const openKey = open ? `${table.id}:${table.schema_version}` : null;
  if (openKey !== null && openKey !== seededAt) {
    setSeededAt(openKey);
    setRows(toRows(table));
  }

  const problems = fieldProblems(error);
  function problemFor(index: number, field: string): string | undefined {
    return problems.find((problem) => problem.field === `columns.${index}.${field}`)?.message;
  }

  function updateRow(key: string, patch: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  function removeRow(key: string) {
    setRows((current) => current.filter((row) => row.key !== key));
  }

  function addOption(key: string) {
    setRows((current) =>
      current.map((row) =>
        row.key === key ? { ...row, options: [...(row.options ?? []), { label: "" }] } : row,
      ),
    );
  }

  function updateOption(key: string, index: number, label: string) {
    setRows((current) =>
      current.map((row) => {
        if (row.key !== key) return row;
        const options = [...(row.options ?? [])];
        options[index] = { ...options[index], label };
        return { ...row, options };
      }),
    );
  }

  function toggleOptionArchived(key: string, index: number) {
    setRows((current) =>
      current.map((row) => {
        if (row.key !== key) return row;
        const options = [...(row.options ?? [])];
        const target = options[index];
        if (target) options[index] = { ...target, archived: !target.archived };
        return { ...row, options };
      }),
    );
  }

  function submit() {
    onSave(rows.map(({ key: _key, ...column }) => column));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          {rows.map((row, index) => (
            <div key={row.key} className="border-border space-y-2 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <Input
                  value={row.label}
                  placeholder={t("labelPlaceholder")}
                  onChange={(event) => updateRow(row.key, { label: event.target.value })}
                  aria-label={t("columnLabel")}
                />
                <Select
                  value={row.type}
                  disabled={!!row.id}
                  onValueChange={(value) => updateRow(row.key, { type: value as ColumnTypeName })}
                >
                  <SelectTrigger className="w-40" aria-label={t("columnType")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COLUMN_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {t(`types.${type}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                  <Checkbox
                    checked={row.nullable ?? true}
                    onCheckedChange={(checked) =>
                      updateRow(row.key, { nullable: checked === true })
                    }
                  />
                  {t("nullable")}
                </label>
                {row.id ? (
                  <label className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                    <Checkbox
                      checked={row.archived ?? false}
                      onCheckedChange={(checked) =>
                        updateRow(row.key, { archived: checked === true })
                      }
                    />
                    {t("archived")}
                  </label>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("removeColumn")}
                    onClick={() => removeRow(row.key)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
              {problemFor(index, "type") && (
                <p className="text-destructive text-xs">{problemFor(index, "type")}</p>
              )}
              {problemFor(index, "default") && (
                <p className="text-destructive text-xs">{problemFor(index, "default")}</p>
              )}
              {problemFor(index, "nullable") && (
                <p className="text-destructive text-xs">{problemFor(index, "nullable")}</p>
              )}
              {(row.type === "single_select" || row.type === "multi_select") && (
                <div className="space-y-1.5 pl-1">
                  {(row.options ?? []).map((option, optionIndex) => (
                    <div key={option.id ?? optionIndex} className="flex items-center gap-2">
                      <Input
                        value={option.label}
                        placeholder={t("optionPlaceholder")}
                        onChange={(event) => updateOption(row.key, optionIndex, event.target.value)}
                        aria-label={t("optionLabel")}
                      />
                      {option.id && (
                        <label className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                          <Checkbox
                            checked={option.archived ?? false}
                            onCheckedChange={() => toggleOptionArchived(row.key, optionIndex)}
                          />
                          {t("archived")}
                        </label>
                      )}
                    </div>
                  ))}
                  {problemFor(index, "options") && (
                    <p className="text-destructive text-xs">{problemFor(index, "options")}</p>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => addOption(row.key)}
                  >
                    <Plus className="h-3.5 w-3.5" /> {t("addOption")}
                  </Button>
                </div>
              )}
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            onClick={() => setRows((current) => [...current, blankRow()])}
          >
            <Plus className="h-4 w-4" /> {t("addColumn")}
          </Button>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button type="button" onClick={submit} disabled={isSaving}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
