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
import { COLUMN_TYPES } from "@/types/tables";
import type { ColumnDef, ColumnInput, ColumnTypeName } from "@/types/tables";

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

/**
 * One new column at the end of the table: a label, a type, and a select's
 * options one per line. It starts optional, so the records already in the
 * table - which hold nothing for it - stay valid; the Columns dialog makes one
 * required with a default.
 */
export function AddColumnDialog({
  open,
  onOpenChange,
  onAdd,
  isSaving,
}: {
  open: boolean;
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
  const needsOptions = SELECTS.has(type);
  const ready = label.trim() !== "" && (!needsOptions || labels.length > 0);

  // Cleared as the dialog closes, however it closes - a column added closes it
  // from the caller - during render rather than in an effect.
  if (useChanged(open) && !open) {
    setLabel("");
    setType("text");
    setOptions("");
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
