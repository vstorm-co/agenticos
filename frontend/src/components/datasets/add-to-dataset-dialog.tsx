"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAddToDataset, useDatasets } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { DatasetTargetFields, type AnswerAs } from "./dataset-target-fields";

interface AddToDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The agent's answer that becomes the case. */
  messageId: string;
  /** Whether the answer was rated down, which decides what it is kept as by default. */
  ratedDown: boolean;
}

/**
 * Which dataset an answer goes into, and whether it is the bad answer or the good one.
 *
 * The question, the turns before it and the rating's comment come with it on the
 * server; this asks only what the server cannot know.
 */
export function AddToDatasetDialog({
  open,
  onOpenChange,
  messageId,
  ratedDown,
}: AddToDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { datasets, isLoading } = useDatasets({ sort: "updated", limit: 100 });
  const add = useAddToDataset();
  const editable = datasets.filter((dataset) => dataset.can_edit);
  const [chosen, setChosen] = useState<string>("");
  const [answerAs, setAnswerAs] = useState<AnswerAs>(
    ratedDown ? "counter_example" : "reference_answer",
  );
  const target = editable.find((dataset) => dataset.id === chosen) ?? editable[0];
  const datasetId = target?.id ?? "";

  async function submit(into: { id: string; name: string }) {
    try {
      await add.mutateAsync({ datasetId: into.id, messageId, answerAs });
      toast.success(t("addedTo", { name: into.name }));
      onOpenChange(false);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("addToDataset")}</DialogTitle>
          <DialogDescription>{t("addToDatasetBody")}</DialogDescription>
        </DialogHeader>
        <DatasetTargetFields
          editable={editable}
          isLoading={isLoading}
          datasetId={datasetId}
          onDatasetChange={setChosen}
          answerAs={answerAs}
          onAnswerAsChange={setAnswerAs}
          idPrefix="add-to-dataset"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={add.isPending || target === undefined}
            onClick={() => target && void submit(target)}
          >
            {t("add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
