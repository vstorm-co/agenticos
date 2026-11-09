"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  FilePenLine,
  FlaskConical,
  History,
  Sparkles,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ListCardEmpty } from "@/components/ui";
import { DatasetIcon } from "./dataset-chip";
import { cn } from "@/lib/utils";
import { ImportCasesDialog } from "./import-cases-dialog";
import type { DatasetTone } from "./dataset-chip";
import { ROUTES } from "@/lib/constants";
import { useDatasetFiles } from "./use-dataset-files";

interface EmptyCasesProps {
  datasetId: string;
  /** Absent for somebody who may not add a case, who is told what the tab holds and nothing more. */
  onAddCase?: () => void;
  onImport?: (file: File) => Promise<unknown>;
  /** Opens the generator; absent where it is not offered. */
  onGenerate?: () => void;
}

/**
 * A version with no case, and the ways one arrives: written here, imported from a
 * file, drafted by the generator, or added from an answer in Activity or a
 * conversation.
 */
export function EmptyCases({ datasetId, onAddCase, onImport, onGenerate }: EmptyCasesProps) {
  const t = useTranslations("datasets");
  const picker = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const { upload } = useDatasetFiles(datasetId, null);

  if (onAddCase === undefined || onImport === undefined) {
    return (
      <ListCardEmpty icon={FlaskConical} title={t("noCases")} description={t("noCasesBody")} />
    );
  }
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-6 space-y-2 text-center">
        <h3 className="text-lg font-semibold tracking-tight">{t("journey.emptyTitle")}</h3>
        <p className="text-muted-foreground mx-auto max-w-xl text-sm leading-relaxed">
          {t("journey.emptyBody")}
        </p>
      </div>
      <div className={cn("grid gap-3 sm:grid-cols-2", onGenerate && "lg:grid-cols-3")}>
        <CreationOption
          title={t("addCase")}
          hint={t("journey.writeHint")}
          icon={FilePenLine}
          tone="blue"
          onClick={onAddCase}
          tour="datasets-add-case"
        />
        <CreationOption
          title={t("import")}
          hint={t("journey.importHint")}
          icon={Upload}
          tone="green"
          onClick={() => setImporting(true)}
        />
        {onGenerate && (
          <CreationOption
            title={t("generateCases")}
            hint={t("journey.generateHint")}
            icon={Sparkles}
            tone="purple"
            onClick={onGenerate}
            tour="datasets-generate-action"
          />
        )}
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-2 text-xs">
        <span className="text-muted-foreground">{t("journey.realAnswers")}</span>
        <Button size="sm" variant="link" asChild>
          <Link href={`${ROUTES.RUNS}?${new URLSearchParams({ dataset: datasetId })}`}>
            <History className="size-3.5" aria-hidden />
            {t("addFromActivity")}
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </Button>
      </div>
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

function CreationOption({
  title,
  hint,
  icon: Icon,
  tone,
  onClick,
  tour,
}: {
  title: string;
  hint: string;
  icon: LucideIcon;
  tone: DatasetTone;
  onClick: () => void;
  tour?: string;
}) {
  return (
    <button
      type="button"
      aria-label={title}
      onClick={onClick}
      data-tour={tour}
      className="group hover:border-foreground/25 hover:bg-accent/30 focus-visible:ring-ring flex flex-col gap-4 rounded-xl border p-5 text-left transition-colors focus-visible:ring-2"
    >
      <DatasetIcon tone={tone} icon={Icon} className="size-10 rounded-xl" />
      <span className="space-y-1.5">
        <span className="flex items-center justify-between gap-2 text-sm font-semibold">
          {title}
          <ArrowRight
            className="text-muted-foreground size-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none"
            aria-hidden
          />
        </span>
        <span className="text-muted-foreground block text-xs leading-relaxed">{hint}</span>
      </span>
    </button>
  );
}
