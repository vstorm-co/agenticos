"use client";

import { useState } from "react";
import Link from "next/link";
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
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAddToDataset, useDatasets, type AddFromMessage } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";

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
  const [answerAs, setAnswerAs] = useState<AddFromMessage["answerAs"]>(
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
          <div className="space-y-4">
            <FormField htmlFor="add-to-dataset" label={t("dataset")}>
              <Select value={datasetId} onValueChange={setChosen}>
                <SelectTrigger id="add-to-dataset">
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
            <FormField htmlFor="add-answer-as" label={t("keepAnswerAs")}>
              <Select
                value={answerAs}
                onValueChange={(next) => setAnswerAs(next as AddFromMessage["answerAs"])}
              >
                <SelectTrigger id="add-answer-as">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="counter_example">{t("field.counter_example")}</SelectItem>
                  <SelectItem value="reference_answer">{t("field.reference_answer")}</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
        )}
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
