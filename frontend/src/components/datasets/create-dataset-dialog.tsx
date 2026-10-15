"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { DatasetDetailsFields } from "./dataset-details-fields";

interface CreateDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * A new, empty dataset, opened as soon as it exists: what comes next - adding
 * its first case, which makes version 1 - happens on its page.
 */
export function CreateDatasetDialog({ open, onOpenChange }: CreateDatasetDialogProps) {
  const t = useTranslations("datasets");
  const router = useRouter();
  const tErrors = useTranslations("errors");
  const { create } = useDatasets();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [shared, setShared] = useState(true);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function handleCreate() {
    try {
      const dataset = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() === "" ? null : description.trim(),
        visibility: shared ? "org" : "private",
      });
      setName("");
      setDescription("");
      setErrors({});
      onOpenChange(false);
      router.push(ROUTES.DATASET_DETAIL(dataset.id));
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
        <p className="text-muted-foreground flex flex-wrap items-center gap-1 text-sm">
          {shared ? t("createVisibleToOrg") : t("createPrivate")}
          <Button
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => setShared((current) => !current)}
          >
            {shared ? t("createMakePrivate") : t("createShareWithOrg")}
          </Button>
        </p>
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
