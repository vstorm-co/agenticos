"use client";

import { useImperativeHandle, useState, type Ref } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Checkbox } from "@/components/ui/checkbox";
import { useAddToDataset } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { DatasetTargetFields } from "./dataset-target-fields";
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
}

/**
 * "Add this answer to a dataset", offered in the dialog that asks what went wrong.
 *
 * A rated-down answer is kept as the counter-example: the rating already said
 * it is wrong. The rating is saved first, so its comment is there to become the
 * case's note. Not rendered for somebody with no dataset to add to.
 */
export function AlsoAddToDataset({ messageId, ref }: AlsoAddToDatasetProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const allowed = useCanAddToDataset();
  const [wanted, setWanted] = useState(false);
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
          await add.mutateAsync({ datasetId: target.id, messageId, answerAs: "counter_example" });
          remember(target);
          toast.success(t("addedTo", { name: target.name }));
        } catch (error) {
          toast.error(t("addAfterRatingFailed", { reason: getErrorMessage(error, tErrors) }));
        }
      },
    }),
    [wanted, target, add, messageId, remember, t, tErrors],
  );

  if (!allowed) return null;
  return (
    <div className="space-y-3 rounded-md border p-3">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={wanted} onCheckedChange={(next) => setWanted(next === true)} />
        {t("alsoAddToDataset")}
      </label>
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
    </div>
  );
}
