"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useEvalComparison } from "@/hooks/use-eval-runs";
import { ROUTES } from "@/lib/constants";
import type { EvalComparison, Flip } from "@/types/eval-runs";
import type { CheckStage, StageCounts } from "@/types/skill-checks";

/** A stage's counts read off its run, for a check judged before they were kept. */
export function countsOf(comparison: EvalComparison): StageCounts {
  const flips = (flip: Flip) => comparison.cases.filter((item) => item.flip === flip).length;
  const fixed = flips("fixed");
  const broken = flips("regression");
  const unchanged = flips("unchanged");
  return {
    compared: fixed + broken + unchanged,
    fixed,
    broken,
    unchanged,
    unknown: flips("incomplete") + comparison.not_compared + comparison.changed,
  };
}

/**
 * What one stage of an agent's check found on its questions: how many came out
 * better, the same, worse or not known, beside the run that asked them. The check
 * keeps these counts; one judged before it did reads them off the run instead.
 */
export function StageBreakdown({
  agentId,
  stage,
  unconfirmed = false,
}: {
  agentId: string;
  stage: CheckStage;
  /** Its flips were not repeated when asked again: the counts are the first answers'. */
  unconfirmed?: boolean;
}) {
  const t = useTranslations("skillImprovement.agents");
  const runId = stage.eval_run_id!;
  const { comparison, error } = useEvalComparison(runId, { enabled: stage.counts === null });
  const counts = stage.counts ?? (comparison ? countsOf(comparison) : null);
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
          ? t(unconfirmed ? "stageCountsFirst" : "stageCounts", {
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
