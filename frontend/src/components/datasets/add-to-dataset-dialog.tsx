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
import { useAddToDataset } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { Dataset } from "@/types/datasets";
import { DatasetTargetFields, type AnswerAs } from "./dataset-target-fields";
import { useDatasetTarget } from "./use-dataset-target";

interface AddToDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The agent's answer that becomes the case. */
  messageId: string;
  /** What the answer is kept as, or what is offered first when `askAnswerAs`. */
  answerAs: AnswerAs;
  /**
   * Whether the reader picks it. True in Activity, where a turn may carry no
   * rating; false after a thumbs-up in chat, where the rating already said.
   */
  askAnswerAs: boolean;
}

/**
 * Which dataset an answer goes into.
 *
 * The question, the turns before it and the rating's comment come with it on the
 * server; this asks only what the server cannot know.
 */
export function AddToDatasetDialog({
  open,
  onOpenChange,
  messageId,
  answerAs: initial,
  askAnswerAs,
}: AddToDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { editable, isLoading, target, choose, remember } = useDatasetTarget();
  const add = useAddToDataset();
  const [answerAs, setAnswerAs] = useState<AnswerAs>(initial);

  async function submit(into: Dataset) {
    try {
      await add.mutateAsync({ datasetId: into.id, messageId, answerAs });
      remember(into);
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
          <DialogDescription>
            {t(askAnswerAs ? "addToDatasetBody" : "addAsReferenceBody")}
          </DialogDescription>
        </DialogHeader>
        <DatasetTargetFields
          editable={editable}
          isLoading={isLoading}
          datasetId={target?.id ?? ""}
          onDatasetChange={choose}
          answerAs={askAnswerAs ? { value: answerAs, onChange: setAnswerAs } : undefined}
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
