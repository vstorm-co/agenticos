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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useCreateJudge } from "@/hooks/use-scoring";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";

const OLDEST = "oldest";

interface CreateJudgeDialogProps {
  dataset: Dataset;
  onOpenChange: (open: boolean) => void;
  /** The dataset as it came back, with the new judge picked. */
  onCreated: (dataset: Dataset) => void;
}

/**
 * A judge of the dataset's own, started from its name and what it is about.
 *
 * The judge is an agent: what is written here is its prompt, which its page
 * edits later. The rubric stays on the dataset.
 */
export function CreateJudgeDialog({ dataset, onOpenChange, onCreated }: CreateJudgeDialogProps) {
  const t = useTranslations("datasets.scoring");
  const tErrors = useTranslations("errors");
  const create = useCreateJudge(dataset.id);
  const { profiles } = useModelProviders();
  const [name, setName] = useState(t("judgeNameFor", { name: dataset.name }));
  const [instructions, setInstructions] = useState(
    t("judgeInstructionsTemplate", {
      name: dataset.name,
      described: dataset.description ? "yes" : "no",
      description: dataset.description ?? "",
    }),
  );
  const [model, setModel] = useState(OLDEST);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function submit() {
    try {
      const updated = await create.mutateAsync({
        name: name.trim(),
        instructions: instructions.trim(),
        model_profile_id: model === OLDEST ? null : model,
      });
      onCreated(updated);
      toast.success(t("judgeCreated", { name: name.trim() }));
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "instructions", "model_profile_id"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("createJudgeTitle", { name: dataset.name })}</DialogTitle>
          <DialogDescription>{t("createJudgeBody")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField htmlFor="judge-name" label={t("judgeName")} error={errors.name}>
            <Input
              id="judge-name"
              value={name}
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>
          <FormField
            htmlFor="judge-instructions"
            label={t("judgeInstructions")}
            error={errors.instructions}
          >
            <Textarea
              id="judge-instructions"
              value={instructions}
              rows={8}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </FormField>
          <FormField htmlFor="judge-model" label={t("judgeModel")} error={errors.model_profile_id}>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger id="judge-model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={OLDEST}>{t("judgeOldestModel")}</SelectItem>
                {profiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={create.isPending || name.trim() === "" || instructions.trim() === ""}
            onClick={() => void submit()}
          >
            {t("createJudge")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
