"use client";

import { useState } from "react";
import { Download, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { saveBlob } from "@/lib/file-access";
import { cn } from "@/lib/utils";
import { IMPORT_COLUMNS, IMPORT_PREVIEW, importTemplate, jsonlTemplate } from "./import-columns";

interface ImportCasesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Opens the file picker; the dialog closes as it does. */
  onChoose: () => void;
}

/**
 * What a dataset file holds, before the file picker opens.
 *
 * The columns are described here rather than learned from a refusal, and the
 * template is a file with every column and one case that imports as it is.
 */
export function ImportCasesDialog({ open, onOpenChange, onChoose }: ImportCasesDialogProps) {
  const t = useTranslations("datasets");
  const [format, setFormat] = useState<"csv" | "jsonl">("csv");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("importTitle")}</DialogTitle>
          <DialogDescription>{t("importBody")}</DialogDescription>
        </DialogHeader>
        <div className={cn(DIALOG_BODY, "space-y-5")}>
          <div role="group" aria-label={t("importFormat")} className="flex gap-2">
            {(["csv", "jsonl"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={format === value ? "secondary" : "outline"}
                aria-pressed={format === value}
                onClick={() => setFormat(value)}
              >
                {value.toUpperCase()}
              </Button>
            ))}
          </div>
          <p className="text-sm">{t("importRequired")}</p>
          <pre className="bg-muted overflow-x-auto rounded-lg border p-3 text-xs break-all whitespace-pre-wrap">
            {IMPORT_PREVIEW[format]}
          </pre>
          <p className="text-muted-foreground text-xs">
            {t(format === "csv" ? "importCsvHint" : "importJsonlHint")}
          </p>
          <dl className="divide-y text-sm">
            {IMPORT_COLUMNS.map((column) => (
              <div key={column} className="grid gap-1 py-2 sm:grid-cols-[11rem_1fr]">
                <dt className="font-mono text-xs leading-5">{column}</dt>
                <dd className="text-muted-foreground">{t(`importColumn.${column}`)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button
            variant="outline"
            onClick={() =>
              saveBlob(
                format === "csv" ? importTemplate() : jsonlTemplate(),
                `dataset-template.${format}`,
              )
            }
          >
            <Download className="h-4 w-4" aria-hidden />
            {t("downloadTemplate")}
          </Button>
          <Button
            onClick={() => {
              onOpenChange(false);
              onChoose();
            }}
          >
            <Upload className="h-4 w-4" aria-hidden />
            {t("chooseFile")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
