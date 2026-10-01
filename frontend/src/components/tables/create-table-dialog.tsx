"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileUp, Plus, Trash2 } from "lucide-react";

import { ColumnTypeIcon } from "./column-type-icon";
import { inferType, readCsvFile } from "./csv-cells";
import {
  Button,
  Dialog,
  DialogContent,
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
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { NO_FAILURE, submitFailure } from "@/lib/api-error";
import { COLUMN_TYPES } from "@/types/tables";
import type { ColumnInput, ColumnTypeName, TableVisibility } from "@/types/tables";

const FORM = { fields: ["name"], identifiedBy: "name" } as const;

/** A table holds at most this many columns; `MAX_COLUMNS` in the service. */
const MAX_COLUMNS = 100;
/** The longest table or column name; `Label` in the service's schema. */
const MAX_LABEL = 64;

interface DraftColumn {
  key: string;
  label: string;
  type: ColumnTypeName;
  /** The file column it was read from, for a table started from a CSV file. */
  source?: number;
}

/** A file a new table was started from: its rows are imported once the table exists. */
export interface CsvStart {
  fileName: string;
  headers: string[];
  rows: string[][];
  /** For each of the file's columns, the label of the column it became; null once removed. */
  labels: (string | null)[];
}

/**
 * A draft column per file column: its header as the label - one that is blank,
 * too long or already taken made unique, as the service refuses two alike - and
 * the type its values read as.
 */
function columnsFrom(
  headers: string[],
  rows: string[][],
  unnamed: (n: number) => string,
): DraftColumn[] {
  const taken = new Set<string>();
  return headers.map((header, at) => {
    const base = header.trim().slice(0, MAX_LABEL).trim() || unnamed(at + 1);
    let label = base;
    for (let n = 2; taken.has(label); n += 1) {
      const suffix = ` ${n}`;
      label = base.slice(0, MAX_LABEL - suffix.length) + suffix;
    }
    taken.add(label);
    return {
      key: crypto.randomUUID(),
      label,
      type: inferType(rows.map((row) => row[at] ?? "")),
      source: at,
    };
  });
}

/** Name, columns, visibility - a table's creation flow, in one dialog. */
export function CreateTableDialog({
  open,
  onOpenChange,
  onCreate,
  isCreating,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (
    input: {
      name: string;
      description: string | null;
      visibility: TableVisibility;
      columns: ColumnInput[];
    },
    csv: CsvStart | null,
  ) => void;
  isCreating: boolean;
  error: unknown;
}) {
  const t = useTranslations("tables.create");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<TableVisibility>("private");
  // A table starts with the column every record is named by; a CSV replaces it.
  const firstColumn = (): DraftColumn[] => [
    { key: crypto.randomUUID(), label: t("firstColumn"), type: "text" },
  ];
  const [columns, setColumns] = useState<DraftColumn[]>(firstColumn);
  const [csv, setCsv] = useState<{
    fileName: string;
    headers: string[];
    rows: string[][];
  } | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);

  // `submitFailure`, not `fieldProblems`: a taken name is a 409 `AlreadyExistsError`
  // reporting a fact about the row that exists (`details: {name}`), not a
  // structured `details.fields` list - `identifiedBy` is what routes a conflict
  // like that to the one input that could have produced it. `.toast` is what is
  // left once the name has claimed its own problem - a duplicate column label,
  // say, which the server refuses on `columns` rather than on any input this
  // form renders. `NO_FAILURE` when `error` is absent: `submitFailure` treats
  // anything that is not an `ApiError` - `null` included - as an unexpected
  // failure and fills `.toast` with a fallback sentence, which would render on
  // a dialog that has not failed at all.
  const failure = error != null ? submitFailure(error, FORM, tErrors) : NO_FAILURE;
  const nameProblem = failure.fields.name;

  function reset() {
    setName("");
    setDescription("");
    setVisibility("private");
    setColumns(firstColumn());
    setCsv(null);
    setCsvError(null);
  }

  async function startFrom(file: File) {
    const read = await readCsvFile(file);
    if (read === null || read.headers.length > MAX_COLUMNS) {
      setCsvError(read === null ? t("csvEmpty") : t("csvTooWide", { max: MAX_COLUMNS }));
      return;
    }
    setCsvError(null);
    setCsv({ fileName: file.name, ...read });
    if (!name.trim()) setName(file.name.replace(/\.csv$/i, "").slice(0, MAX_LABEL));
    setColumns(columnsFrom(read.headers, read.rows, (n) => t("csvColumn", { n })));
  }

  function submit() {
    // The only caller is the footer's Create button, which is `disabled` for
    // a blank name - a disabled button fires no click, so `submit` never runs
    // with an empty `name` and this needs no guard of its own.
    const kept = columns.filter((column) => column.label.trim());
    onCreate(
      {
        name: name.trim(),
        description: description.trim() || null,
        visibility,
        columns: kept.map((column) => ({ label: column.label.trim(), type: column.type })),
      },
      csv && {
        ...csv,
        labels: csv.headers.map(
          (_, at) => kept.find((column) => column.source === at)?.label.trim() ?? null,
        ),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // This dialog renders no `DialogTrigger` of its own - `open` is driven
        // entirely by the caller - so Radix only ever invokes this with
        // `false`, from an in-dialog close (Escape, overlay, the close
        // button). Resetting unconditionally is therefore equivalent to
        // resetting on close, without a branch that never takes its other arm.
        reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>
        {/* Grows a row per column, so it scrolls and the footer's Create stays on screen. */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <div className="space-y-1.5" data-tour="table-dialog-name">
            <Label htmlFor="table-name">{t("nameLabel")}</Label>
            <Input
              id="table-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              aria-invalid={nameProblem ? true : undefined}
            />
            {nameProblem && <p className="text-destructive text-xs">{nameProblem}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="table-description">{t("descriptionLabel")}</Label>
            <Textarea
              id="table-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("descriptionPlaceholder")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="table-visibility">{t("visibilityLabel")}</Label>
            <Select
              value={visibility}
              onValueChange={(next) => setVisibility(next as TableVisibility)}
            >
              <SelectTrigger id="table-visibility" data-tour="table-dialog-visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">{t("visibility.private")}</SelectItem>
                <SelectItem value="team">{t("visibility.team")}</SelectItem>
                <SelectItem value="org">{t("visibility.org")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label className="border-border hover:bg-accent/40 flex cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-sm">
              <FileUp aria-hidden="true" className="text-muted-foreground size-4" />
              <span className="min-w-0 flex-1 truncate">
                {csv === null
                  ? t("fromCsv")
                  : t("fromCsvChosen", { file: csv.fileName, count: csv.rows.length })}
              </span>
              <input
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                aria-label={t("fromCsv")}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void startFrom(file);
                }}
              />
            </label>
            <p className="text-muted-foreground text-xs">
              {csv === null ? t("fromCsvHint") : t("fromCsvTypes")}
            </p>
            {csvError !== null && <p className="text-destructive text-xs">{csvError}</p>}
          </div>
          <div className="space-y-2" data-tour="table-dialog-columns">
            <p className="text-sm font-medium">{t("columnsHeading")}</p>
            {columns.map((column) => (
              <div key={column.key} className="flex items-center gap-2">
                <Input
                  value={column.label}
                  placeholder={t("columnPlaceholder")}
                  aria-label={t("columnLabel")}
                  onChange={(event) =>
                    setColumns((current) =>
                      current.map((c) =>
                        c.key === column.key ? { ...c, label: event.target.value } : c,
                      ),
                    )
                  }
                />
                <Select
                  value={column.type}
                  onValueChange={(value) =>
                    setColumns((current) =>
                      current.map((c) =>
                        c.key === column.key ? { ...c, type: value as ColumnTypeName } : c,
                      ),
                    )
                  }
                >
                  <SelectTrigger className="w-40" aria-label={t("columnType")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COLUMN_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        <span className="inline-flex items-center gap-2">
                          <ColumnTypeIcon type={type} />
                          {t(`types.${type}`)}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t("removeColumn")}
                  onClick={() =>
                    setColumns((current) => current.filter((c) => c.key !== column.key))
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setColumns((current) => [
                  ...current,
                  { key: crypto.randomUUID(), label: "", type: "text" },
                ])
              }
            >
              <Plus className="h-3.5 w-3.5" /> {t("addColumn")}
            </Button>
          </div>
        </div>
        {failure.toast !== null && <p className="text-destructive text-sm">{failure.toast}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={isCreating || !name.trim()}
            data-tour="table-dialog-create"
          >
            {t("submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
