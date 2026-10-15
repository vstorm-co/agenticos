"use client";

import { useRef } from "react";
import Link from "next/link";
import { FlaskConical, Plus, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ListCardEmpty } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { useDatasetFiles } from "./use-dataset-files";

interface EmptyCasesProps {
  datasetId: string;
  /** Absent for somebody who may not add a case, who is told what the tab holds and nothing more. */
  onAddCase?: () => void;
  onImport?: (file: File) => Promise<unknown>;
}

/**
 * A version with no case, and the three ways one arrives: written here, imported
 * from a file, or added from an answer in Activity or a conversation.
 */
export function EmptyCases({ datasetId, onAddCase, onImport }: EmptyCasesProps) {
  const t = useTranslations("datasets");
  const picker = useRef<HTMLInputElement>(null);
  const { upload } = useDatasetFiles(datasetId, null);

  if (onAddCase === undefined || onImport === undefined) {
    return (
      <ListCardEmpty icon={FlaskConical} title={t("noCases")} description={t("noCasesBody")} />
    );
  }
  return (
    <div>
      <ListCardEmpty icon={FlaskConical} title={t("noCases")} description={t("noCasesBody")} />
      <div className="-mt-10 flex flex-wrap justify-center gap-2 pb-12">
        <Button size="sm" onClick={onAddCase}>
          <Plus className="h-4 w-4" />
          {t("addCase")}
        </Button>
        <input
          ref={picker}
          type="file"
          accept=".csv,.jsonl,.ndjson"
          className="hidden"
          aria-label={t("importFile")}
          onChange={(event) => void upload(event.currentTarget, onImport)}
        />
        <Button size="sm" variant="outline" onClick={() => picker.current?.click()}>
          <Upload className="h-4 w-4" />
          {t("import")}
        </Button>
        <Button size="sm" variant="outline" asChild>
          <Link href={ROUTES.RUNS}>{t("addFromActivity")}</Link>
        </Button>
      </div>
    </div>
  );
}
