"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useChanged } from "@/hooks/use-changed";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { useTable, useTables } from "@/hooks";
import { AGGREGATES, COLUMN_TYPES, REFERENCE_TYPES } from "@/types/tables";
import type { Aggregate, ColumnDef, ColumnInput, ColumnTypeName } from "@/types/tables";

/** The whole column list a schema change submits, every column as the table has it now. */
export function currentColumns(columns: ColumnDef[]): ColumnInput[] {
  return columns.map((column) => ({
    id: column.id,
    label: column.label,
    type: column.type,
    nullable: column.nullable,
    default: column.default,
    options: column.options.map((option) => ({ ...option })),
    archived: column.archived,
    // What a link, lookup or rollup names goes back with every change: the
    // service refuses one sent without it.
    link_table_id: column.link_table_id ?? null,
    link_column_id: column.link_column_id ?? null,
    target_column_id: column.target_column_id ?? null,
    aggregate: column.aggregate ?? null,
  }));
}

/** A new label for one column - every record keeps its values, since a column is matched by id. */
export function RenameColumnDialog({
  column,
  onOpenChange,
  onRename,
  isSaving,
}: {
  /** The column being renamed; `null` keeps the dialog closed. */
  column: ColumnDef | null;
  onOpenChange: (open: boolean) => void;
  onRename: (column: ColumnDef, label: string) => void;
  isSaving: boolean;
}) {
  const t = useTranslations("tables.columnMenu");
  const [label, setLabel] = useState(column?.label ?? "");
  const [seen, setSeen] = useState(column);
  if (column !== seen) {
    setSeen(column);
    setLabel(column?.label ?? "");
  }
  const trimmed = label.trim();

  return (
    <Dialog open={column !== null} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("renameTitle")}</DialogTitle>
          <DialogDescription>{t("renameDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (column && trimmed) onRename(column, trimmed);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="rename-column">{t("label")}</Label>
            <Input
              id="rename-column"
              value={label}
              maxLength={64}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={isSaving || !trimmed || trimmed === column?.label}>
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const SELECTS = new Set<ColumnTypeName>(["single_select", "multi_select"]);
/** What a sum or an average reads, and what a minimum or maximum can also read. */
const SUMMED = new Set<ColumnTypeName>(["number", "integer", "rating"]);
const ORDERED = new Set<ColumnTypeName>([...SUMMED, "date", "datetime"]);

/** What a link, lookup or rollup column names, as the dialog is filling it in. */
interface Reference {
  linkTableId: string;
  linkColumnId: string;
  targetColumnId: string;
  aggregate: Aggregate;
}

const NO_REFERENCE: Reference = {
  linkTableId: "",
  linkColumnId: "",
  targetColumnId: "",
  aggregate: "count",
};

/** Whether a linked table's column suits what a lookup or a rollup does with it. */
function readable(column: ColumnDef, type: ColumnTypeName, aggregate: Aggregate): boolean {
  if (column.archived || REFERENCE_TYPES.has(column.type)) return false;
  if (type === "lookup") return true;
  if (aggregate === "sum" || aggregate === "avg") return SUMMED.has(column.type);
  return ORDERED.has(column.type);
}

/**
 * The fields a link, lookup or rollup column needs: the table a link points at,
 * or the link a lookup reads through, the column it reads there and what a
 * rollup works out from it.
 */
function ReferenceFields({
  type,
  columns,
  value,
  onChange,
}: {
  type: ColumnTypeName;
  columns: ColumnDef[];
  value: Reference;
  onChange: (next: Reference) => void;
}) {
  const t = useTranslations("tables.columnMenu");
  const { tables } = useTables({ limit: 100 });
  const links = columns.filter((column) => column.type === "link" && !column.archived);
  const link = links.find((column) => column.id === value.linkColumnId) ?? null;
  const { table: target } = useTable(link?.link_table_id ?? null);
  const counts = type === "rollup" && value.aggregate === "count";
  const choices = (target?.columns ?? []).filter((column) =>
    readable(column, type, value.aggregate),
  );

  if (type === "link") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor="new-column-link-table">{t("linkTable")}</Label>
        <Select
          value={value.linkTableId}
          onValueChange={(next) => onChange({ ...value, linkTableId: next })}
        >
          <SelectTrigger id="new-column-link-table">
            <SelectValue placeholder={t("linkTablePlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {tables.map((table) => (
              <SelectItem key={table.id} value={table.id}>
                {table.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }
  if (links.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("needsLink")}</p>;
  }
  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="new-column-link-column">{t("throughLink")}</Label>
        <Select
          value={value.linkColumnId}
          onValueChange={(next) => onChange({ ...value, linkColumnId: next, targetColumnId: "" })}
        >
          <SelectTrigger id="new-column-link-column">
            <SelectValue placeholder={t("throughLinkPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {links.map((column) => (
              <SelectItem key={column.id} value={column.id}>
                {column.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {type === "rollup" && (
        <div className="space-y-1.5">
          <Label htmlFor="new-column-aggregate">{t("aggregate")}</Label>
          <Select
            value={value.aggregate}
            onValueChange={(next) =>
              onChange({ ...value, aggregate: next as Aggregate, targetColumnId: "" })
            }
          >
            <SelectTrigger id="new-column-aggregate">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {AGGREGATES.map((aggregate) => (
                <SelectItem key={aggregate} value={aggregate}>
                  {t(`aggregates.${aggregate}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {link !== null && !counts && (
        <div className="space-y-1.5">
          <Label htmlFor="new-column-target">{t("reads")}</Label>
          <Select
            value={value.targetColumnId}
            onValueChange={(next) => onChange({ ...value, targetColumnId: next })}
          >
            <SelectTrigger id="new-column-target">
              <SelectValue placeholder={t("readsPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {choices.map((column) => (
                <SelectItem key={column.id} value={column.id}>
                  {column.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </>
  );
}

/** The fields a new column of `type` sends for what it names; empty for any other type. */
function referenceInput(type: ColumnTypeName, reference: Reference): Partial<ColumnInput> {
  if (type === "link") return { link_table_id: reference.linkTableId };
  if (type === "lookup") {
    return { link_column_id: reference.linkColumnId, target_column_id: reference.targetColumnId };
  }
  if (type === "rollup") {
    return {
      link_column_id: reference.linkColumnId,
      aggregate: reference.aggregate,
      target_column_id: reference.aggregate === "count" ? null : reference.targetColumnId,
    };
  }
  return {};
}

/** Whether what a column of `type` names has been chosen. */
function referenceReady(type: ColumnTypeName, reference: Reference): boolean {
  if (type === "link") return reference.linkTableId !== "";
  if (type === "lookup") return reference.linkColumnId !== "" && reference.targetColumnId !== "";
  if (type === "rollup") {
    return (
      reference.linkColumnId !== "" &&
      (reference.aggregate === "count" || reference.targetColumnId !== "")
    );
  }
  return true;
}

/**
 * One new column at the end of the table: a label, a type, and a select's
 * options one per line. It starts optional, so the records already in the
 * table - which hold nothing for it - stay valid; the Columns dialog makes one
 * required with a default.
 */
export function AddColumnDialog({
  open,
  columns,
  onOpenChange,
  onAdd,
  isSaving,
}: {
  open: boolean;
  /** The table's columns, which a lookup or rollup reads through one of. */
  columns: ColumnDef[];
  onOpenChange: (open: boolean) => void;
  onAdd: (column: ColumnInput) => void;
  isSaving: boolean;
}) {
  const t = useTranslations("tables.columnMenu");
  const tTypes = useTranslations("tables.schema.types");
  const [label, setLabel] = useState("");
  const [type, setType] = useState<ColumnTypeName>("text");
  const [options, setOptions] = useState("");
  const labels = [...new Set(options.split("\n").map((line) => line.trim()))].filter(Boolean);
  const [reference, setReference] = useState<Reference>(NO_REFERENCE);
  const needsOptions = SELECTS.has(type);
  const ready =
    label.trim() !== "" && (!needsOptions || labels.length > 0) && referenceReady(type, reference);

  // Cleared as the dialog closes, however it closes - a column added closes it
  // from the caller - during render rather than in an effect.
  if (useChanged(open) && !open) {
    setLabel("");
    setType("text");
    setOptions("");
    setReference(NO_REFERENCE);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("addTitle")}</DialogTitle>
          <DialogDescription>{t("addDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!ready) return;
            onAdd({
              label: label.trim(),
              type,
              nullable: true,
              options: needsOptions ? labels.map((option) => ({ label: option })) : [],
              ...referenceInput(type, reference),
            });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="new-column-label">{t("label")}</Label>
            <Input
              id="new-column-label"
              value={label}
              maxLength={64}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-column-type">{t("type")}</Label>
            <Select value={type} onValueChange={(next) => setType(next as ColumnTypeName)}>
              <SelectTrigger id="new-column-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COLUMN_TYPES.map((name) => (
                  <SelectItem key={name} value={name}>
                    {tTypes(name)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {REFERENCE_TYPES.has(type) && (
            <ReferenceFields
              type={type}
              columns={columns}
              value={reference}
              onChange={setReference}
            />
          )}
          {needsOptions && (
            <div className="space-y-1.5">
              <Label htmlFor="new-column-options">{t("options")}</Label>
              <Textarea
                id="new-column-options"
                value={options}
                rows={4}
                placeholder={t("optionsPlaceholder")}
                onChange={(event) => setOptions(event.target.value)}
              />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={isSaving || !ready}>
              {t("add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
