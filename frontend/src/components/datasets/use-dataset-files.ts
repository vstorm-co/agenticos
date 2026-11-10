"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { exportDataset } from "@/hooks/use-datasets";
import { fieldProblems, getErrorMessage } from "@/lib/api-error";
import type { DatasetFileFormat } from "@/types/datasets";

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

/**
 * Export the version on screen, and import a CSV or JSONL file as a new version.
 *
 * Failures are toasts. An import is all or nothing, and a refused one says which
 * rows - that sentence comes from the server and is shown as it is.
 */
export function useDatasetFiles(datasetId: string, version: number | null) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");

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

  return { download, upload };
}
