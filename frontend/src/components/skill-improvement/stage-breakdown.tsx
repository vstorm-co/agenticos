"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useEvalComparison } from "@/hooks/use-eval-runs";
import { ROUTES } from "@/lib/constants";
import type { CheckStage } from "@/types/skill-checks";

/**
 * What one stage of an agent's check found on its questions: how many came out
 * better, the same, worse or not known, beside the run that asked them. Read only
 * once the agent's row is opened, since each stage is a comparison of its own.
 */
export function StageBreakdown({ agentId, stage }: { agentId: string; stage: CheckStage }) {
  const t = useTranslations("skillImprovement.agents");
  const runId = stage.eval_run_id!;
  const { comparison, error } = useEvalComparison(runId);
  const better = comparison ? comparison.fixed_confirmed + comparison.fixed_unconfirmed : 0;
  const worse = comparison
    ? comparison.regressions_confirmed + comparison.regressions_unconfirmed
    : 0;
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
        {error
          ? t("stageUnread")
          : comparison
            ? t("stageCounts", {
                better,
                same: comparison.compared - better - worse,
                worse,
                unknown: comparison.not_compared,
              })
            : t("stageLoading")}
      </span>
    </li>
  );
}
