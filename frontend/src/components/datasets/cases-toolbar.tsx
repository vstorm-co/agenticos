"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, History, Plus, Sparkles, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { ImportCasesDialog } from "./import-cases-dialog";
import { useDatasetFiles } from "./use-dataset-files";

/** Case creation belongs with the table, and stays discoverable after its first row. */
export function CasesToolbar({
  datasetId,
  onAdd,
  onImport,
  onGenerate,
}: {
  datasetId: string;
  onAdd: () => void;
  onImport: (file: File) => Promise<unknown>;
  onGenerate: () => void;
}) {
  const t = useTranslations("datasets");
  const [importing, setImporting] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const { upload } = useDatasetFiles(datasetId, null);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Button data-tour="datasets-add-case" size="sm" onClick={onAdd}>
        <Plus className="size-4" />
        {t("addCase")}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline">
            {t("moreSources")}
            <ChevronDown className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setImporting(true)}>
            <Upload className="size-4" />
            {t("import")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onGenerate}>
            <Sparkles className="size-4" />
            {t("generateCases")}
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link href={`${ROUTES.RUNS}?${new URLSearchParams({ dataset: datasetId })}`}>
              <History className="size-4" />
              {t("addFromActivity")}
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <input
        ref={picker}
        type="file"
        accept=".csv,.jsonl,.ndjson"
        className="hidden"
        aria-label={t("importFile")}
        onChange={(event) => void upload(event.currentTarget, onImport)}
      />
      <ImportCasesDialog
        open={importing}
        onOpenChange={setImporting}
        onChoose={() => picker.current?.click()}
      />
    </div>
  );
}
