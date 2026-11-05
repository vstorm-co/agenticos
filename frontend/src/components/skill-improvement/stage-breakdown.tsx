"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useEvalComparison } from "@/hooks/use-eval-runs";
import { ROUTES } from "@/lib/constants";
import type { CheckStage, StageCounts } from "@/types/skill-checks";

/**
 * What one stage of an agent's check found on its questions: how many came out
 * better, the same, worse or not known, beside the run that asked them. The check
 * keeps these counts; one judged before it did reads them off the run instead.
 */
export function StageBreakdown({ agentId, stage }: { agentId: string; stage: CheckStage }) {
  const t = useTranslations("skillImprovement.agents");
  const runId = stage.eval_run_id!;
  const kept = stage.counts ?? null;
  // A check judged before counts were kept is read off its run, only for this row.
  const { comparison, error } = useEvalComparison(runId, { enabled: kept === null });
  const counts: StageCounts | null =
    kept ??
    (comparison
      ? {
          compared: comparison.compared,
          fixed: comparison.fixed_confirmed + comparison.fixed_unconfirmed,
          broken: comparison.regressions_confirmed + comparison.regressions_unconfirmed,
          unchanged:
            comparison.compared -
            comparison.fixed_confirmed -
            comparison.fixed_unconfirmed -
            comparison.regressions_confirmed -
            comparison.regressions_unconfirmed,
          unknown: comparison.not_compared,
        }
      : null);
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-xs">
      <Link
        className="underline underline-offset-4"
        href={`${ROUTES.AGENT_DETAIL(agentId)}/evals/${runId}`}
      >
        {t(`stage.${stage.kind}`, {
          name: stage.dataset_name ?? "",
          named: stage.dataset_name === null ? "no" : "yes",
        })}
      </Link>
      <span className="text-muted-foreground">
        {counts
          ? t("stageCounts", {
              better: counts.fixed,
              same: counts.unchanged,
              worse: counts.broken,
              unknown: counts.unknown,
            })
          : error
            ? t("stageUnread")
            : t("stageLoading")}
      </span>
    </li>
  );
}
