"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useDatasets } from "@/hooks/use-datasets";
import { useAddKnowledgeGapToDataset } from "@/hooks/use-knowledge-gaps";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";

interface GapToDatasetDialogProps {
  topicId: string;
  onClose: () => void;
}

/**
 * Which dataset a topic's questions become cases of. Only datasets the caller
 * may change are offered; the server answers how many were added and how many
 * it skipped for having no answer the caller may read.
 */
export function GapToDatasetDialog({ topicId, onClose }: GapToDatasetDialogProps) {
  const t = useTranslations("knowledgeGaps");
  const { datasets, isLoading } = useDatasets({ sort: "updated", limit: 100 });
  const add = useAddKnowledgeGapToDataset();
  const editable = datasets.filter((dataset) => dataset.can_edit);
  const [chosen, setChosen] = useState("");
  const target = editable.find((dataset) => dataset.id === chosen) ?? editable[0];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("addToDataset")}</DialogTitle>
          <DialogDescription>{t("addToDatasetBody")}</DialogDescription>
        </DialogHeader>
        {!isLoading && editable.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.rich("noDatasetToAddTo", {
              link: (chunks) => (
                <Link href={ROUTES.DATASETS} className="underline">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        ) : (
          <FormField htmlFor="gap-to-dataset" label={t("dataset")}>
            <Select value={target?.id ?? ""} onValueChange={setChosen}>
              <SelectTrigger id="gap-to-dataset">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {editable.map((dataset) => (
                  <SelectItem key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            disabled={add.isPending || target === undefined}
            onClick={() =>
              target &&
              add.mutate(
                { topicId, datasetId: target.id, name: target.name },
                { onSuccess: onClose },
              )
            }
          >
            {t("add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
