"use client";

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
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { saveBlob } from "@/lib/file-access";
import { IMPORT_COLUMNS, importTemplate } from "./import-columns";

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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("importTitle")}</DialogTitle>
          <DialogDescription>{t("importBody")}</DialogDescription>
        </DialogHeader>
        <dl className="space-y-1.5 text-sm">
          {IMPORT_COLUMNS.map((column) => (
            <div key={column} className="flex flex-wrap gap-x-2">
              <dt className="font-mono text-xs leading-5">{column}</dt>
              <dd className="text-muted-foreground">{t(`importColumn.${column}`)}</dd>
            </div>
          ))}
        </dl>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button
            variant="outline"
            onClick={() => saveBlob(importTemplate(), "dataset-template.csv")}
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
