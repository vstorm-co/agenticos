"use client";

import { useRef } from "react";
import { Download, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { exportDataset } from "@/hooks/use-datasets";
import { fieldProblems, getErrorMessage } from "@/lib/api-error";
import type { DatasetFileFormat } from "@/types/datasets";

interface DatasetFileActionsProps {
  datasetId: string;
  /** The version on screen, which is the one exported; null is the newest. */
  version: number | null;
  /** Absent for somebody who may read the dataset but not change it. */
  onImport?: (file: File) => Promise<unknown>;
}

/**
 * Import a CSV or JSONL file as a new version, and export the version on screen.
 *
 * An import is all or nothing, and a refused one says which rows - that sentence
 * comes from the server and is shown as it is.
 */
/** How many refused rows a toast lists; the server names at most twenty. */
const SHOWN_ROWS = 5;

/**
 * The rows an import was refused for, one line each, as the server named them.
 *
 * The server reports `rows.<n>` for a row it could not read and `rows.<n>.<field>`
 * for a field that failed, numbered from the first data row or line.
 */
export function refusedRows(
  error: unknown,
  t: (key: string, values: Record<string, string | number>) => string,
): string | undefined {
  const lines = fieldProblems(error).flatMap((problem) => {
    const named = /^rows\.(\d+)(?:\.(.+))?$/.exec(problem.field);
    if (named === null) return [];
    const [, row, field] = named;
    return field === undefined
      ? [t("importRowProblem", { row: Number(row), message: problem.message })]
      : [t("importRowFieldProblem", { row: Number(row), field, message: problem.message })];
  });
  return lines.length === 0 ? undefined : lines.slice(0, SHOWN_ROWS).join("\n");
}

export function DatasetFileActions({ datasetId, version, onImport }: DatasetFileActionsProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const picker = useRef<HTMLInputElement>(null);

  async function download(format: DatasetFileFormat) {
    try {
      await exportDataset(datasetId, { format, version });
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  }

  async function upload(input: HTMLInputElement, send: (file: File) => Promise<unknown>) {
    const [file] = input.files ?? [];
    // Cleared first, so choosing the same file again after fixing it fires a change.
    input.value = "";
    if (file === undefined) return;
    try {
      await send(file);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors), { description: refusedRows(error, t) });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-tour="dataset-file-actions">
      {onImport !== undefined && (
        <>
          <input
            ref={picker}
            type="file"
            accept=".csv,.jsonl,.ndjson"
            className="hidden"
            aria-label={t("importFile")}
            onChange={(event) => void upload(event.currentTarget, onImport)}
          />
          <Button
            variant="outline"
            size="sm"
            data-tour="datasets-import"
            onClick={() => picker.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            {t("import")}
          </Button>
        </>
      )}
      <Button variant="outline" size="sm" onClick={() => void download("csv")}>
        <Download className="h-3.5 w-3.5" aria-hidden />
        {t("exportCsv")}
      </Button>
      <Button variant="outline" size="sm" onClick={() => void download("jsonl")}>
        <Download className="h-3.5 w-3.5" aria-hidden />
        {t("exportJsonl")}
      </Button>
    </div>
  );
}
