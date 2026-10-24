"use client";

import { useImperativeHandle, useState, type Ref } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Checkbox } from "@/components/ui/checkbox";
import { useAddToDataset } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DatasetTargetFields } from "./dataset-target-fields";
import { asksAboutHistory, type AskedBefore } from "./follows-on";
import { HistoryChoice } from "./history-choice";
import { useCanAddToDataset, useDatasetTarget } from "./use-dataset-target";

export interface AlsoAddToDatasetHandle {
  /**
   * Add the answer to the dataset chosen, when one was. Never throws: whether it
   * worked is said in a toast, because the rating it follows stands either way.
   */
  addIfChosen: () => Promise<void>;
}

interface AlsoAddToDatasetProps {
  messageId: string;
  ref: Ref<AlsoAddToDatasetHandle>;
  /** The question the answer replied to, when the chat can see it. */
  asked?: AskedBefore;
}

/**
 * "Add this answer to a dataset", offered in the dialog that asks what went wrong.
 *
 * A rated-down answer is kept as the counter-example: the rating already said
 * it is wrong. The rating is saved first, so its comment is there to become the
 * case's note. Not rendered for somebody with no dataset to add to.
 */
export function AlsoAddToDataset({ messageId, ref, asked }: AlsoAddToDatasetProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const allowed = useCanAddToDataset();
  const [wanted, setWanted] = useState(false);
  const [withHistory, setWithHistory] = useState(false);
  const { editable, isLoading, search, target, choose, remember } = useDatasetTarget({
    enabled: allowed && wanted,
  });
  const add = useAddToDataset();

  useImperativeHandle(
    ref,
    () => ({
      async addIfChosen() {
        if (!wanted || target === undefined) return;
        try {
          await add.mutateAsync({
            datasetId: target.id,
            messageId,
            answerAs: "counter_example",
            withHistory,
          });
          remember(target);
          toast.success(t("addedTo", { name: target.name }), {
            action: {
              label: t("openDataset"),
              onClick: () => router.push(`${ROUTES.DATASET_DETAIL(target.id)}?tab=cases`),
            },
          });
        } catch (error) {
          toast.error(t("addAfterRatingFailed", { reason: getErrorMessage(error, tErrors) }));
        }
      },
    }),
    [wanted, target, add, messageId, withHistory, remember, router, t, tErrors],
  );

  if (!allowed) return null;
  return (
    <div className="space-y-3 rounded-md border p-3">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={wanted} onCheckedChange={(next) => setWanted(next === true)} />
        {t("alsoAddToDataset")}
      </label>
      <p className="text-muted-foreground text-xs">{t("alsoAddAsCounterExample")}</p>
      {wanted && (
        <DatasetTargetFields
          editable={editable}
          isLoading={isLoading}
          datasetId={target?.id ?? ""}
          onDatasetChange={choose}
          search={search}
          idPrefix="rate-down"
        />
      )}
      {wanted && asksAboutHistory(asked) && (
        <HistoryChoice
          idPrefix="rate-down"
          withHistory={withHistory}
          onChange={setWithHistory}
          asked={asked}
        />
      )}
    </div>
  );
}
