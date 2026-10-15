"use client";

import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { useDataset } from "@/hooks/use-datasets";
import { useRescoreRun } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalRun } from "@/types/eval-runs";
import { sideName } from "./names";
import { quoted } from "./verdict-headline";
import { Perm } from "@/types/permissions";

/**
 * The run's answers no scorer reached a verdict on - the judge failed or was
 * skipped - which count as neither passed nor failed: each side's cases, one
 * quoted, to grade again before deciding, for who may run the dataset. The
 * agent is not asked again.
 */
export function UngradedNote({ run }: { run: EvalRun }) {
  const t = useTranslations("evals.ungraded");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { dataset } = useDataset(run.dataset_id);
  const rescore = useRescoreRun(run.dataset_id);
  const tSide = useTranslations("evals");
  const ids = run.ungraded_score_ids;
  if (ids.length === 0) return null;
  const sides = run.arms.flatMap((arm) => {
    const [first, ...rest] = arm.ungraded_cases;
    return first ? [{ arm, first, others: rest.length }] : [];
  });
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {sides.length === 0 ? (
        <span className="text-muted-foreground">{t("count", { count: ids.length })}</span>
      ) : (
        sides.map(({ arm, first, others }) => (
          <span key={arm.id} className="text-warning block w-full">
            {t("side", {
              count: others + 1,
              side: sideName(arm, tSide),
              question: quoted(first.input),
              others,
            })}
          </span>
        ))
      )}
      {(can(Perm.datasetsRun) || dataset?.can_edit) && (
        <Button
          size="sm"
          variant="outline"
          disabled={rescore.isPending}
          onClick={() =>
            rescore.mutate(ids, {
              onSuccess: (count) => toast.success(t("done", { count })),
              onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
            })
          }
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          {t("again")}
        </Button>
      )}
    </div>
  );
}
