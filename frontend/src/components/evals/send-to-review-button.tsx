"use client";

import { Inbox } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { useDataset } from "@/hooks/use-datasets";
import { useSendToReview } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalRun, EvalRunArm } from "@/types/eval-runs";

/**
 * Sends a side's failed answers to the dataset's review queue, where a person
 * can overturn a grade. Offered to who may edit the dataset, and only when
 * something failed.
 */
export function SendToReviewButton({ run, arm }: { run: EvalRun; arm: EvalRunArm }) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const { dataset } = useDataset(run.dataset_id);
  const send = useSendToReview(run.id, run.dataset_id);
  // What the run did not already send itself, nor a person before.
  const failed = arm.unsent_failed;
  if (!dataset?.can_edit || failed === 0) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={send.isPending}
      onClick={() =>
        send.mutate(arm.id, {
          onSuccess: (sent) => toast.success(t("review.sent", sent)),
          onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
        })
      }
    >
      <Inbox className="h-3.5 w-3.5" aria-hidden />
      {run.routed_to_review > 0
        ? t("review.sendOther", { count: failed })
        : t("review.send", { count: failed })}
    </Button>
  );
}
