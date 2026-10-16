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
import { useDatasets } from "@/hooks/use-datasets";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { Dataset } from "@/types/datasets";
import { DatasetDetailsFields } from "./dataset-details-fields";

interface CreateDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (dataset: Dataset) => void;
}

/** A new, empty dataset. Its first case makes version 1. */
export function CreateDatasetDialog({ open, onOpenChange, onCreated }: CreateDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { create } = useDatasets();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function handleCreate() {
    try {
      const dataset = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() === "" ? null : description.trim(),
      });
      setName("");
      setDescription("");
      setErrors({});
      onOpenChange(false);
      onCreated?.(dataset);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("newDataset")}</DialogTitle>
          <DialogDescription>{t("newDatasetBody")}</DialogDescription>
        </DialogHeader>
        <DatasetDetailsFields
          name={name}
          onNameChange={setName}
          description={description}
          onDescriptionChange={setDescription}
          errors={errors}
          nameTour="datasets-dialog-name"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            data-tour="datasets-create-submit"
            disabled={create.isPending || name.trim() === ""}
            onClick={() => void handleCreate()}
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
