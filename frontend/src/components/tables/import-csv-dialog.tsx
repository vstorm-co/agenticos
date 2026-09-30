"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Upload } from "lucide-react";

import { type CellProblem, readCell, readCsvFile } from "./csv-cells";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Progress,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";
import { batchRefusal, createRecords } from "@/lib/tables-api";
import type { CellValue, ColumnDef, RecordCreate } from "@/types/tables";

/** Records sent in one request: the service's batch limit. */
const BATCH = 200;
const SKIP = "__skip__";
const EXTERNAL_ID = "__external_id__";
/** Failures listed on screen; the count says how many more there were. */
const SHOWN_FAILURES = 50;

interface Failure {
  /** The row's line in the file, the header being line 1. */
  line: number;
  reason: string;
}

type Step =
  | { name: "pick"; error: string | null }
  | { name: "map"; fileName: string; headers: string[]; rows: string[][] }
  | { name: "importing"; done: number; total: number }
  | { name: "done"; created: number; failures: Failure[] };

/** A file read before the dialog opened, and where each of its columns goes. */
export interface CsvPreset {
  fileName: string;
  headers: string[];
  rows: string[][];
  /** The column id each header goes to, in header order; null for one not imported. */
  mapping: (string | null)[];
}

/** The table column a file's header goes to by default: the one of the same name, if any. */
function guess(header: string, columns: ColumnDef[]): string {
  const name = header.trim().toLowerCase();
  if (name === "external_id" || name === "external id") return EXTERNAL_ID;
  return columns.find((column) => column.label.trim().toLowerCase() === name)?.id ?? SKIP;
}

/**
 * Records from a CSV file: pick it, say which column each of its columns goes
 * to, and import - a batch at a time, so a file of thousands never holds one
 * request open, with the progress in view and every row that did not make it
 * listed with its line and the reason.
 *
 * A cell that cannot be read as its column's type fails its row before anything
 * is sent; the service then refuses what it refuses (a taken external id, a
 * table that is full), one row at a time rather than the whole file. Each record
 * created is the member's own write, so a table trigger starts for it.
 */
export function ImportCsvDialog({
  tableId,
  columns,
  open,
  onOpenChange,
  preset,
}: {
  tableId: string;
  /** The table's live columns - where a file's columns can go. */
  columns: ColumnDef[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A file already read and mapped, to open on: the table was just made from it. */
  preset?: CsvPreset;
}) {
  const t = useTranslations("tables.import");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>(
    preset ? { name: "map", ...preset } : { name: "pick", error: null },
  );
  const [mapping, setMapping] = useState<string[]>(
    preset?.mapping.map((target) => target ?? SKIP) ?? [],
  );

  const close = (next: boolean) => {
    if (step.name === "importing") return;
    if (!next) setStep({ name: "pick", error: null });
    onOpenChange(next);
  };

  const pick = async (file: File) => {
    const read = await readCsvFile(file);
    if (read === null) {
      setStep({ name: "pick", error: t("empty") });
      return;
    }
    setMapping(read.headers.map((header) => guess(header, columns)));
    setStep({ name: "map", fileName: file.name, ...read });
  };

  const byId = new Map(columns.map((column) => [column.id, column]));
  const problemText = (column: ColumnDef, problem: CellProblem) =>
    t("cellProblem", { column: column.label, problem: t(`problem.${problem}`) });

  /** One row as a record, or why it cannot be one. */
  const toRecord = (row: string[]): { record: RecordCreate } | { reason: string } => {
    const values: Record<string, CellValue> = {};
    let externalId: string | null = null;
    for (const [at, target] of mapping.entries()) {
      const raw = row[at] ?? "";
      if (target === SKIP) continue;
      if (target === EXTERNAL_ID) {
        externalId = raw.trim() || null;
        continue;
      }
      const column = byId.get(target) as ColumnDef;
      const read = readCell(column, raw);
      if ("problem" in read) return { reason: problemText(column, read.problem) };
      if (read.value !== null) values[column.id] = read.value;
    }
    return { record: { external_id: externalId, values } };
  };

  const run = async (rows: string[][]) => {
    const failures: Failure[] = [];
    const ready: { line: number; record: RecordCreate }[] = [];
    rows.forEach((row, index) => {
      const line = index + 2;
      const read = toRecord(row);
      if ("reason" in read) failures.push({ line, reason: read.reason });
      else ready.push({ line, record: read.record });
    });
    let created = 0;
    setStep({ name: "importing", done: 0, total: ready.length });
    for (let start = 0; start < ready.length; start += BATCH) {
      const batch = ready.slice(start, start + BATCH);
      try {
        const result = await createRecords(
          tableId,
          batch.map((entry) => entry.record),
        );
        created += result.created;
        for (const failure of result.failed) {
          failures.push({
            line: (batch[failure.index] as (typeof batch)[number]).line,
            reason: getErrorMessage(batchRefusal(failure), tErrors),
          });
        }
      } catch (error) {
        // A refusal of the whole batch - a rate limit, the table archived - stops
        // the import there: every row not yet sent is listed, not guessed at.
        const reason = getErrorMessage(error, tErrors);
        for (const entry of ready.slice(start)) failures.push({ line: entry.line, reason });
        break;
      }
      setStep({
        name: "importing",
        done: Math.min(start + BATCH, ready.length),
        total: ready.length,
      });
    }
    await queryClient.invalidateQueries({ queryKey: qk.tables.recordsAll(tableId) });
    failures.sort((a, b) => a.line - b.line);
    setStep({ name: "done", created, failures });
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={`${DIALOG_SCROLL} sm:max-w-2xl`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {step.name === "pick" && (
          <div className="space-y-2">
            <label className="border-border hover:bg-accent/40 flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-10 text-center text-sm">
              <Upload aria-hidden="true" className="text-muted-foreground size-5" />
              <span>{t("choose")}</span>
              <span className="text-muted-foreground text-xs">{t("chooseHint")}</span>
              <input
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                aria-label={t("choose")}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void pick(file);
                }}
              />
            </label>
            {step.error !== null && <p className="text-destructive text-sm">{step.error}</p>}
          </div>
        )}

        {step.name === "map" && (
          <div className="space-y-3">
            <p className="text-muted-foreground text-sm">
              {t("found", { file: step.fileName, count: step.rows.length })}
            </p>
            <div className="border-border divide-border divide-y rounded-lg border">
              {step.headers.map((header, at) => (
                <div key={at} className="flex items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{header || t("unnamed")}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {step.rows
                        .slice(0, 3)
                        .map((row) => row[at] ?? "")
                        .join(" · ")}
                    </p>
                  </div>
                  <Select
                    value={mapping[at] ?? SKIP}
                    onValueChange={(next) =>
                      setMapping(mapping.map((target, index) => (index === at ? next : target)))
                    }
                  >
                    <SelectTrigger className="w-48" aria-label={t("mapTo", { header })}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={SKIP}>{t("skip")}</SelectItem>
                      <SelectItem value={EXTERNAL_ID}>{t("externalId")}</SelectItem>
                      {columns.map((column) => (
                        <SelectItem key={column.id} value={column.id}>
                          {column.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          </div>
        )}

        {step.name === "importing" && (
          <div className="space-y-2 py-4">
            <Progress value={step.total === 0 ? 100 : (step.done / step.total) * 100} />
            <p className="text-muted-foreground text-center text-sm tabular-nums">
              {t("progress", { done: step.done, total: step.total })}
            </p>
          </div>
        )}

        {step.name === "done" && (
          <div className="space-y-3">
            <p className="text-sm">{t("created", { count: step.created })}</p>
            {step.failures.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-destructive text-sm">
                  {t("failed", { count: step.failures.length })}
                </p>
                <ul className="border-border max-h-60 space-y-1 overflow-y-auto rounded-lg border p-2 text-xs">
                  {step.failures.slice(0, SHOWN_FAILURES).map((failure) => (
                    <li key={failure.line}>
                      <span className="text-muted-foreground tabular-nums">
                        {t("line", { line: failure.line })}
                      </span>{" "}
                      {failure.reason}
                    </li>
                  ))}
                </ul>
                {step.failures.length > SHOWN_FAILURES && (
                  <p className="text-muted-foreground text-xs">
                    {t("more", { count: step.failures.length - SHOWN_FAILURES })}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step.name === "map" && (
            <>
              <Button variant="outline" onClick={() => setStep({ name: "pick", error: null })}>
                {t("back")}
              </Button>
              <Button
                disabled={mapping.every((target) => target === SKIP)}
                onClick={() => void run(step.rows)}
              >
                {t("import", { count: step.rows.length })}
              </Button>
            </>
          )}
          {(step.name === "pick" || step.name === "done") && (
            <Button variant="outline" onClick={() => close(false)}>
              {t("close")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
