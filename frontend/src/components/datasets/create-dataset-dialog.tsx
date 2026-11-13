"use client";

import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { ArrowRight, FlaskConical, ListChecks, Play, Scale } from "lucide-react";
import { DatasetChip, DatasetIcon } from "./dataset-chip";
import { useId, useState } from "react";
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
  FormField,
  Input,
  Label,
  MoreOptions,
  Textarea,
} from "@/components/ui";
import { useDatasets } from "@/hooks/use-datasets";
import { submitFailure } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { AudiencePicker, EVERYONE, type Audience } from "@/components/sharing/audience-picker";

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
  const ta = useTranslations("audience");
  const router = useRouter();
  const tErrors = useTranslations("errors");
  const { create } = useDatasets();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [audience, setAudience] = useState<Audience>(EVERYONE);
  const [moreOpen, setMoreOpen] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  function edit(field: "name" | "description", value: string) {
    if (field === "name") setName(value);
    else setDescription(value);
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  const source = useId();
  function reset() {
    setName("");
    setDescription("");
    setErrors({});
    setAudience(EVERYONE);
    setMoreOpen(false);
  }
  useUnsavedChanges(source, {
    dirty: open && (name !== "" || description !== "" || audience.mode !== EVERYONE.mode),
    save: name.trim() !== "" ? handleCreate : undefined,
    discard: () => {
      reset();
      onOpenChange(false);
    },
  });
  // This dialog has no trigger: only dismissal asks to change its open state.
  function close() {
    if (!create.isPending)
      useUnsavedChangesStore.getState().leave(() => onOpenChange(false), [source]);
  }

  async function handleCreate(): Promise<boolean> {
    if (create.isPending || name.trim() === "") return false;
    try {
      const dataset = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() === "" ? null : description.trim(),
        visibility: audience.mode === "private" ? "private" : "org",
      });
      reset();
      onOpenChange(false);
      router.push(ROUTES.DATASET_DETAIL(dataset.id));
      return true;
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.fields.description) setMoreOpen(true);
      if (failure.toast) toast.error(failure.toast);
      return false;
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent dismissible={!create.isPending} className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <DatasetIcon tone="blue" icon={FlaskConical} className="size-9" />
            {t("newDataset")}
          </DialogTitle>
          <DialogDescription>{t("newDatasetBody")}</DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          <fieldset disabled={create.isPending} className="min-w-0 space-y-4">
            <legend className="sr-only">{t("newDataset")}</legend>
            <FormField htmlFor="dataset-name" label={t("name")} error={errors.name} required>
              <Input
                data-tour="datasets-dialog-name"
                maxLength={120}
                value={name}
                placeholder={t("namePlaceholder")}
                onChange={(event) => edit("name", event.target.value)}
              />
            </FormField>
            <div className="space-y-1.5">
              <Label>{ta("label")}</Label>
              <AudiencePicker
                value={audience}
                onChange={setAudience}
                withChosen={false}
                disabled={create.isPending}
              />
            </div>
            <MoreOptions label={t("moreOptions")} open={moreOpen} onOpenChange={setMoreOpen}>
              <FormField
                htmlFor="dataset-description"
                label={t("description")}
                error={errors.description}
              >
                <Textarea
                  rows={2}
                  maxLength={500}
                  value={description}
                  placeholder={t("descriptionPlaceholder")}
                  onChange={(event) => edit("description", event.target.value)}
                />
              </FormField>
            </MoreOptions>
          </fieldset>
        </div>
        <div className="bg-muted/30 space-y-2 rounded-xl border p-3">
          <p className="text-muted-foreground text-xs">{t("journey.afterCreate")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <DatasetChip tone="blue" icon={ListChecks}>
              {t("cases")}
            </DatasetChip>
            <ArrowRight className="text-muted-foreground size-3" aria-hidden />
            <DatasetChip tone="purple" icon={Scale}>
              {t("scoring.title")}
            </DatasetChip>
            <ArrowRight className="text-muted-foreground size-3" aria-hidden />
            <DatasetChip tone="green" icon={Play}>
              {t("evals")}
            </DatasetChip>
          </div>
        </div>
        <DialogFooter className="border-t">
          <Button variant="outline" onClick={close} disabled={create.isPending}>
            {t("cancel")}
          </Button>
          <Button
            data-tour="datasets-create-submit"
            loading={create.isPending}
            disabled={name.trim() === ""}
            onClick={() => void handleCreate()}
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
