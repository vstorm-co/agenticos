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
  Label,
  Textarea,
} from "@/components/ui";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { useModelProviders } from "@/hooks/use-model-providers";
import { usePermissions } from "@/hooks/use-permissions";
import { useCreateJudge, useJudgeTemplate } from "@/hooks/use-scoring";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import type { ModelProfile } from "@/types/providers";

/** The model a judge is offered first: the organization's oldest, which the server would pick. */
function oldest(profiles: ModelProfile[]): ModelProfile | undefined {
  return profiles.toSorted(
    (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id.localeCompare(b.id),
  )[0];
}

interface CreateJudgeDialogProps {
  dataset: Dataset;
  onOpenChange: (open: boolean) => void;
  /** The dataset as it came back, with the new judge picked. */
  onCreated: (dataset: Dataset) => void;
}

/**
 * A judge of the dataset's own, started from the default judge's rules of
 * grading and what the dataset is about, as the server writes them.
 *
 * The judge is an agent: what is written here is its prompt, which its page
 * edits later, and what it must know to grade - a policy the cases do not
 * repeat - is added to that prompt. The rubric stays on the dataset.
 */
export function CreateJudgeDialog({ dataset, onOpenChange, onCreated }: CreateJudgeDialogProps) {
  const t = useTranslations("datasets.scoring");
  const tErrors = useTranslations("errors");
  const create = useCreateJudge(dataset.id);
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const [name, setName] = useState(t("judgeNameFor", { name: dataset.name }));
  const template = useJudgeTemplate(dataset.id);
  // The template arrives after the dialog opens; it fills the field once, and an
  // edit made before it arrives is kept.
  const [instructions, setInstructions] = useState<string | null>(null);
  const shown = instructions ?? template.instructions ?? "";
  const [knowledge, setKnowledge] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const model = chosen ?? oldest(profiles)?.id ?? null;
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function submit() {
    try {
      const updated = await create.mutateAsync({
        name: name.trim(),
        instructions: shown.trim() === "" ? null : shown.trim(),
        knowledge: knowledge.trim() === "" ? null : knowledge.trim(),
        model_profile_id: model,
      });
      onCreated(updated);
      toast.success(t("judgeCreated", { name: name.trim() }));
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: ["name", "instructions", "knowledge", "model_profile_id"],
          identifiedBy: "name",
        },
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
              value={shown}
              rows={8}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </FormField>
          <FormField
            htmlFor="judge-knowledge"
            label={t("judgeKnowledge")}
            description={t("judgeKnowledgeHint")}
            error={errors.knowledge}
          >
            <Textarea
              id="judge-knowledge"
              value={knowledge}
              rows={4}
              maxLength={20_000}
              placeholder={t("judgeKnowledgePlaceholder")}
              onChange={(event) => setKnowledge(event.target.value)}
            />
          </FormField>
          <div role="group" aria-labelledby="judge-model" className="space-y-2">
            <Label id="judge-model">{t("judgeModel")}</Label>
            {model === null && (
              <p className="text-muted-foreground text-xs">{t("judgeNoModelYet")}</p>
            )}
            {/* Adding a model is `connections:manage`, which a dataset editor need not
                hold; without it the picker lists the saved models. */}
            <ModelProfilePicker
              allowAdd={can(Perm.connectionsManage)}
              profiles={profiles}
              profilesStatus={profilesStatus}
              value={model}
              onChange={setChosen}
            />
            {errors.model_profile_id && (
              <p role="alert" className="text-destructive text-xs">
                {errors.model_profile_id}
              </p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={create.isPending || name.trim() === ""} onClick={() => void submit()}>
            {t("createJudge")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
