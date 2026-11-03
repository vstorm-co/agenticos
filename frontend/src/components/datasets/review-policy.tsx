"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SettingsSection } from "@/components/settings/settings-section";
import { useSetScoring } from "@/hooks/use-scoring";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage } from "@/lib/api-error";
import type { Dataset } from "@/types/datasets";
import type { ReviewSelect } from "@/types/scoring";

export function ReviewPolicy({ dataset }: { dataset: Dataset }) {
  const t = useTranslations("datasets.scoring");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const stored = dataset.scoring.review.select;
  const [select, setSelect] = useState<ReviewSelect>(stored);
  const [base, setBase] = useState(stored);
  if (base !== stored) {
    setBase(stored);
    if (select === base) setSelect(stored);
  }
  const mutation = useSetScoring(dataset.id);
  const dirty = select !== stored;
  async function save() {
    try {
      await mutation.mutateAsync({ ...dataset.scoring, review: { select } });
      toast.success(t("saved"));
      return true;
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      return false;
    }
  }
  useUnsavedChanges(`review-policy:${dataset.id}`, {
    dirty,
    save,
    discard: () => setSelect(stored),
  });
  return (
    <SettingsSection title={t("reviewCard.title")} description={t("reviewCard.description")}>
      <div className="flex flex-wrap items-end gap-3">
        <FormField htmlFor="scoring-review" label={t("reviewSelect")} className="min-w-0 flex-1">
          <Select
            value={select}
            onValueChange={(value) => setSelect(value as ReviewSelect)}
            disabled={!dataset.can_edit || mutation.isPending}
          >
            <SelectTrigger id="scoring-review">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["none", "failed", "all"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`review.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {dirty && (
          <Button disabled={mutation.isPending} onClick={() => void save()}>
            {tc("save")}
          </Button>
        )}
      </div>
    </SettingsSection>
  );
}
