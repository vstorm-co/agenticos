"use client";

import { useImperativeHandle, useState, type Ref } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Checkbox } from "@/components/ui/checkbox";
import { useAddToDataset, useDatasets } from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import { DatasetTargetFields, type AnswerAs } from "./dataset-target-fields";

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
 * The rating is saved first, so its comment is already there to become the
 * case's note. Not rendered for somebody whose role edits no dataset.
 */
export function AlsoAddToDataset({ messageId, ref }: AlsoAddToDatasetProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const allowed = can(Perm.datasetsEdit);
  const [wanted, setWanted] = useState(false);
  const { datasets, isLoading } = useDatasets({
    sort: "updated",
    limit: 100,
    enabled: allowed && wanted,
  });
  const add = useAddToDataset();
  const editable = datasets.filter((dataset) => dataset.can_edit);
  const [chosen, setChosen] = useState("");
  const [answerAs, setAnswerAs] = useState<AnswerAs>("counter_example");
  const target = editable.find((dataset) => dataset.id === chosen) ?? editable[0];

  useImperativeHandle(
    ref,
    () => ({
      async addIfChosen() {
        if (!wanted || target === undefined) return;
        try {
          await add.mutateAsync({ datasetId: target.id, messageId, answerAs });
          toast.success(t("addedTo", { name: target.name }));
        } catch (error) {
          toast.error(t("addAfterRatingFailed", { reason: getErrorMessage(error, tErrors) }));
        }
      },
    }),
    [wanted, target, add, messageId, answerAs, t, tErrors],
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
          onDatasetChange={setChosen}
          answerAs={answerAs}
          onAnswerAsChange={setAnswerAs}
          idPrefix="rate-down"
        />
      )}
    </div>
  );
}
