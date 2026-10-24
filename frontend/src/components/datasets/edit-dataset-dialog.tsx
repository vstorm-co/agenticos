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
  FormField,
  Input,
} from "@/components/ui";
import type { NewDataset } from "@/hooks/use-datasets";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { Dataset } from "@/types/datasets";
import { DatasetDetailsFields } from "./dataset-details-fields";

interface EditDatasetDialogProps {
  dataset: Dataset;
  onOpenChange: (open: boolean) => void;
  /** `useDataset`'s update, so the page that shows the dataset is the one refreshed. */
  update: { mutateAsync: (changes: NewDataset) => Promise<unknown>; isPending: boolean };
}

/** Rename or redescribe a dataset. Neither is a new version: no case changes. */
export function EditDatasetDialog({ dataset, onOpenChange, update }: EditDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const originalShare = dataset.improvement_holdout_share ?? "0.5";
  const [holdout, setHoldout] = useState(String(Math.round(Number(originalShare) * 1000) / 10));
  const validShare =
    /^(?:100(?:\.0)?|\d{1,2}(?:\.\d)?)$/.test(holdout) &&
    Number.isFinite(Number(holdout)) &&
    Number(holdout) >= 0 &&
    Number(holdout) <= 100;
  const [name, setName] = useState(dataset.name);
  const [description, setDescription] = useState(dataset.description ?? "");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function handleSave() {
    try {
      await update.mutateAsync({
        ...(Number((Number(holdout) / 100).toFixed(3)) !== Number(originalShare)
          ? { improvement_holdout_share: (Number(holdout) / 100).toFixed(3) }
          : {}),
        name: name.trim(),
        description: description.trim() === "" ? null : description.trim(),
      });
      toast.success(t("detailsSaved"));
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description", "improvement_holdout_share"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("editDetails")}</DialogTitle>
          <DialogDescription>{t("editDetailsBody")}</DialogDescription>
        </DialogHeader>
        <DatasetDetailsFields
          name={name}
          onNameChange={setName}
          description={description}
          onDescriptionChange={setDescription}
          errors={errors}
        />
        <FormField
          htmlFor="improvement-holdout-share"
          label={t("improvementSplit.share")}
          description={t("improvementSplit.shareHint")}
          error={
            errors.improvement_holdout_share ??
            (!validShare ? t("improvementSplit.shareInvalid") : undefined)
          }
        >
          <Input
            id="improvement-holdout-share"
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={holdout}
            onChange={(event) => setHoldout(event.target.value)}
          />
        </FormField>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={update.isPending || name.trim() === "" || !validShare}
            onClick={() => void handleSave()}
          >
            {t("saveDetails")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
