"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Archive, ArchiveRestore, Plus, Trash2 } from "lucide-react";
import {
  Button,
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
  Switch,
} from "@/components/ui";
import { cn } from "@/lib/utils";

import { ColumnTypeIcon } from "./column-type-icon";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { fieldProblems, getErrorMessage, schemaDependents } from "@/lib/api-error";
import { SchemaDependents } from "./schema-dependents";
import { COLUMN_CONVERSIONS, COLUMN_TYPES } from "@/types/tables";
import type { ColumnInput, ColumnTypeName, TableRead } from "@/types/tables";

/** An option row, `archived` narrowed to required - see `Row` below. */
interface OptionRow {
  id?: string;
  label: string;
  archived: boolean;
}

interface Row extends Omit<ColumnInput, "options"> {
  /** A stable React key independent of the backend id - a new column has none yet. */
  key: string;
  /** The type the column is saved with, for one that exists: what it may change from. */
  savedType?: ColumnTypeName;
  // Narrowed from `ColumnInput`'s optional versions: every `Row` this module
  // constructs (`toRows`, `blankRow`) sets all three, so nothing downstream
  // needs a fallback for "not set yet".
  nullable: boolean;
  archived: boolean;
  options: OptionRow[];
}

function toRows(table: TableRead): Row[] {
  return table.columns.map((column) => ({
    key: column.id,
    id: column.id,
    label: column.label,
    type: column.type,
    savedType: column.type,
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

const OPTION_TYPES: ReadonlySet<ColumnTypeName> = new Set(["single_select", "multi_select"]);

/** The types a row may be set to: any for a new column, what it converts to for a saved one. */
function typesFor(row: Row): ColumnTypeName[] {
  if (row.savedType === undefined) return [...COLUMN_TYPES];
  const reachable = new Set([row.savedType, ...COLUMN_CONVERSIONS[row.savedType]]);
  return COLUMN_TYPES.filter((type) => reachable.has(type));
}

function blankRow(): Row {
  return {
    key: crypto.randomUUID(),
    label: "",
    type: "text",
    nullable: true,
    archived: false,
    options: [],
  };
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
  const tErrors = useTranslations("errors");
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
  // A schema-version conflict names no field at all (`details.current_version`),
  // so `problems` is empty for it even though the save failed - without this,
  // Save would appear to do nothing. A dependency refusal lists what to change
  // instead (`SchemaDependents`).
  const generalError =
    error != null && problems.length === 0 && schemaDependents(error) === null
      ? getErrorMessage(error, tErrors)
      : null;

  function updateRow(key: string, patch: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  function removeRow(key: string) {
    setRows((current) => current.filter((row) => row.key !== key));
  }

  function addOption(key: string) {
    setRows((current) =>
      current.map((row) =>
        row.key === key
          ? { ...row, options: [...row.options, { label: "", archived: false }] }
          : row,
      ),
    );
  }

  function updateOption(key: string, index: number, label: string) {
    setRows((current) =>
      current.map((row) => {
        if (row.key !== key) return row;
        const options = [...row.options];
        // `index` always comes from mapping over this same `options` array
        // (see the JSX below), so it is always a valid index into it.
        options[index] = { ...(options[index] as OptionRow), label };
        return { ...row, options };
      }),
    );
  }

  /**
   * Drop an unsaved option outright. A saved one (it has an `id`) is never
   * removed this way - archiving is the only way to retire it, since the
   * server still holds records with that option's id in their cells.
   */
  function removeOption(key: string, index: number) {
    setRows((current) =>
      current.map((row) =>
        row.key === key ? { ...row, options: row.options.filter((_, i) => i !== index) } : row,
      ),
    );
  }

  function toggleOptionArchived(key: string, index: number) {
    setRows((current) =>
      current.map((row) => {
        if (row.key !== key) return row;
        const options = [...row.options];
        // `index` always comes from mapping over this same `options` array
        // (see the JSX below), so it is always a valid index into it.
        const target = options[index] as OptionRow;
        options[index] = { ...target, archived: !target.archived };
        return { ...row, options };
      }),
    );
  }

  function submit() {
    onSave(
      rows.map(({ key: _key, savedType, ...column }) => {
        const retyped = savedType !== undefined && column.type !== savedType;
        return {
          ...column,
          // A default of the old type is not one of the new; a choice's options
          // are not text's, and text becoming a choice takes its own values.
          default: retyped ? null : column.default,
          options: OPTION_TYPES.has(column.type) ? column.options : [],
        };
      }),
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          {rows.map((row, index) =>
            row.archived ? null : (
              <div key={row.key} className="border-border space-y-2 rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Input
                    value={row.label}
                    placeholder={t("labelPlaceholder")}
                    onChange={(event) => updateRow(row.key, { label: event.target.value })}
                    aria-label={t("columnLabel")}
                    aria-invalid={problemFor(index, "label") ? true : undefined}
                  />
                  <Select
                    value={row.type}
                    onValueChange={(value) => updateRow(row.key, { type: value as ColumnTypeName })}
                  >
                    <SelectTrigger className="w-44" aria-label={t("columnType")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {typesFor(row).map((type) => (
                        <SelectItem key={type} value={type}>
                          <span className="inline-flex items-center gap-2">
                            <ColumnTypeIcon type={type} />
                            {t(`types.${type}`)}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                    <Switch
                      id={`${row.key}-required`}
                      checked={!row.nullable}
                      onCheckedChange={(on) => updateRow(row.key, { nullable: !on })}
                    />
                    <label htmlFor={`${row.key}-required`}>{t("required")}</label>
                  </div>
                  {row.id ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground size-8 shrink-0"
                      aria-label={t("archiveColumn", { column: row.label })}
                      title={t("archiveColumn", { column: row.label })}
                      onClick={() => updateRow(row.key, { archived: true })}
                    >
                      <Archive className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground size-8 shrink-0"
                      aria-label={t("removeColumn")}
                      onClick={() => removeRow(row.key)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                {problemFor(index, "label") && (
                  <p className="text-destructive text-xs">{problemFor(index, "label")}</p>
                )}
                {row.savedType !== undefined && row.type !== row.savedType && (
                  <p className="text-muted-foreground text-xs">
                    {t(
                      row.type === "single_select" && !OPTION_TYPES.has(row.savedType)
                        ? "retypeToChoice"
                        : "retype",
                      {
                        from: t(`types.${row.savedType}`),
                        to: t(`types.${row.type}`),
                      },
                    )}
                  </p>
                )}
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
                    {row.options.map((option, optionIndex) => (
                      <div key={option.id ?? optionIndex} className="flex items-center gap-2">
                        <Input
                          value={option.label}
                          placeholder={t("optionPlaceholder")}
                          disabled={option.archived}
                          className={cn(option.archived && "line-through opacity-60")}
                          onChange={(event) =>
                            updateOption(row.key, optionIndex, event.target.value)
                          }
                          aria-label={t("optionLabel")}
                        />
                        {option.id ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="text-muted-foreground size-8 shrink-0"
                            aria-label={
                              option.archived
                                ? t("restoreOption", { option: option.label })
                                : t("archiveOption", { option: option.label })
                            }
                            title={
                              option.archived
                                ? t("restoreOption", { option: option.label })
                                : t("archiveOption", { option: option.label })
                            }
                            onClick={() => toggleOptionArchived(row.key, optionIndex)}
                          >
                            {option.archived ? (
                              <ArchiveRestore className="h-4 w-4" />
                            ) : (
                              <Archive className="h-4 w-4" />
                            )}
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="text-muted-foreground size-8 shrink-0"
                            aria-label={t("removeOption")}
                            onClick={() => removeOption(row.key, optionIndex)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
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
            ),
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => setRows((current) => [...current, blankRow()])}
          >
            <Plus className="h-4 w-4" /> {t("addColumn")}
          </Button>
          {rows.some((row) => row.archived) && (
            // Archived, a column keeps its values but leaves every form and view;
            // restoring it brings them back.
            <section className="space-y-1.5 pt-2">
              <h3 className="text-muted-foreground text-xs font-medium">{t("archivedHeading")}</h3>
              {rows
                .filter((row) => row.archived)
                .map((row) => (
                  <div
                    key={row.key}
                    className="border-border text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-3 py-1.5 text-sm"
                  >
                    <ColumnTypeIcon type={row.type} />
                    <span className="min-w-0 flex-1 truncate">{row.label}</span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => updateRow(row.key, { archived: false })}
                    >
                      <ArchiveRestore className="h-4 w-4" /> {t("restore")}
                    </Button>
                  </div>
                ))}
            </section>
          )}
        </div>
        {generalError && <p className="text-destructive text-sm">{generalError}</p>}
        <SchemaDependents error={error} />
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
