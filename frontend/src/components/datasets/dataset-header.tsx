"use client";

import { useRef, useState, type ReactNode } from "react";
import { Download, MoreHorizontal, Pencil, Plus, Share2, Trash2, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Dataset } from "@/types/datasets";
import { ImportCasesDialog } from "./import-cases-dialog";
import { useDatasetFiles } from "./use-dataset-files";

interface DatasetHeaderProps {
  dataset: Dataset;
  /** The version on screen, which is the one exported; null is the newest. */
  version: number | null;
  /** The dataset's own run controls, drawn left of Add case. */
  actions?: ReactNode;
  /** Absent when no case can be added: an older version, or no right to edit. */
  onAddCase?: () => void;
  /** Absent in the same cases as `onAddCase`. */
  onImport?: (file: File) => Promise<unknown>;
  onEditDetails: () => void;
  onShare: () => void;
  /** Asks for the deletion; the page owns the confirmation and the call. */
  onDelete: () => void;
}

/**
 * A dataset's name, the one action it is opened for, and the rest behind a menu.
 *
 * Adding a case is the button; renaming, sharing, files and deleting are rarer and
 * share the menu. Edit details and Delete are drawn only for a caller who may edit
 * the dataset. Export is off while the dataset holds no case.
 */
export function DatasetHeader({
  dataset,
  version,
  actions,
  onAddCase,
  onImport,
  onEditDetails,
  onShare,
  onDelete,
}: DatasetHeaderProps) {
  const t = useTranslations("datasets");
  const picker = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const { download, upload } = useDatasetFiles(dataset.id, version);
  const empty = dataset.case_count === 0;

  return (
    <PageHeader
      title={dataset.name}
      description={dataset.description ?? undefined}
      breadcrumbs={[{ label: t("title"), href: ROUTES.DATASETS }, { label: dataset.name }]}
      badges={
        dataset.latest_version > 0 ? (
          <Badge variant="outline">{t("versionNumber", { number: dataset.latest_version })}</Badge>
        ) : undefined
      }
      actions={
        <>
          {actions}
          {onAddCase !== undefined && (
            <Button data-tour="datasets-add-case" onClick={onAddCase}>
              <Plus className="h-4 w-4" />
              {t("addCase")}
            </Button>
          )}
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
              <ImportCasesDialog
                open={importing}
                onOpenChange={setImporting}
                onChoose={() => picker.current?.click()}
              />
            </>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                aria-label={t("moreActions")}
                data-tour="datasets-menu"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {dataset.can_edit && (
                <DropdownMenuItem onSelect={onEditDetails}>
                  <Pencil className="h-4 w-4" />
                  {t("editDetails")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={onShare}>
                <Share2 className="h-4 w-4" />
                {t("share")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {onImport !== undefined && (
                <DropdownMenuItem onSelect={() => setImporting(true)}>
                  <Upload className="h-4 w-4" />
                  {t("import")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem disabled={empty} onSelect={() => void download("csv")}>
                <Download className="h-4 w-4" />
                {t("exportCsv")}
              </DropdownMenuItem>
              <DropdownMenuItem disabled={empty} onSelect={() => void download("jsonl")}>
                <Download className="h-4 w-4" />
                {t("exportJsonl")}
              </DropdownMenuItem>
              {dataset.can_edit && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={onDelete}
                  >
                    <Trash2 className="h-4 w-4" />
                    {t("delete")}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      }
    />
  );
}
