"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EvalRunVerdict } from "@/components/evals/eval-run-verdict";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useScores } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn, formatDateTime } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";
import type { CaseScore } from "@/types/scoring";

/** As many of a judge's grades as the row shows before "See all". */
const SHOWN = 5;

function Outcome({ score }: { score: CaseScore }) {
  const t = useTranslations("datasets.scoring");
  if (score.outcome === null) return <Badge variant="secondary">{t("unscored")}</Badge>;
  return score.outcome ? (
    <Badge variant="outline">{t("passed")}</Badge>
  ) : (
    <Badge variant="destructive">{t("failed")}</Badge>
  );
}

/** The eval runs among a judge's latest grades, newest first, each once. */
function evalRuns(scores: CaseScore[]): { id: string; agentId: string; at: string }[] {
  const runs = new Map<string, { id: string; agentId: string; at: string }>();
  for (const score of scores) {
    if (score.eval_run_id === null || score.agent_id === null || runs.has(score.eval_run_id)) {
      continue;
    }
    runs.set(score.eval_run_id, {
      id: score.eval_run_id,
      agentId: score.agent_id,
      at: score.created_at,
    });
  }
  return [...runs.values()];
}

/** What one judge graded in one dataset: its latest grades and the eval runs they came from. */
function JudgeDatasetGrades({ datasetId, judgeId }: { datasetId: string; judgeId: string }) {
  const t = useTranslations("agents");
  const tScoring = useTranslations("datasets.scoring");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { scores, isLoading, error } = useScores(datasetId, { judgeId, limit: SHOWN });
  const review = `${ROUTES.DATASET_DETAIL(datasetId)}?tab=review`;

  if (isLoading) return <LoadingState variant="skeleton-list" rows={2} />;
  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (scores.length === 0) {
    return <p className="text-muted-foreground text-xs">{t("judgeDatasetNothing")}</p>;
  }
  const runs = evalRuns(scores);
  return (
    <div className="space-y-3">
      {runs.length > 0 && (
        <ul aria-label={t("judgeDatasetEvalRuns")} className="flex flex-wrap gap-x-3 gap-y-1">
          {runs.map((run) => (
            <li key={run.id} className="flex items-center gap-1.5">
              <Link
                href={`${ROUTES.AGENTS}/${run.agentId}/evals/${run.id}`}
                className="text-xs underline"
              >
                {tScoring("groupEvalRun", { when: formatDateTime(run.at, locale) })}
              </Link>
              <EvalRunVerdict runId={run.id} />
            </li>
          ))}
        </ul>
      )}
      <ul aria-label={t("judgeDatasetGrades")} className="space-y-1.5">
        {scores.map((score) => (
          <li key={score.id} className="flex flex-wrap items-center gap-2 text-xs">
            <Outcome score={score} />
            <span className="min-w-0 flex-1 truncate">{score.question}</span>
            <span className="text-muted-foreground">
              {formatDateTime(score.created_at, locale)}
            </span>
            {score.run_id !== null && (
              <Link href={`${ROUTES.RUNS}?run=${score.run_id}`} className="underline">
                {t("judgeDatasetAnswer")}
              </Link>
            )}
          </li>
        ))}
      </ul>
      <Link href={review} className="text-xs font-medium underline">
        {t("judgeDatasetSeeAll")}
      </Link>
    </div>
  );
}

/**
 * One dataset of a judge, a link to its Grading tab, that opens on what the judge
 * graded there. The grades are read only once the row is opened.
 */
export function JudgeDatasetRow({ dataset, judgeId }: { dataset: Dataset; judgeId: string }) {
  const t = useTranslations("agents");
  const [open, setOpen] = useState(false);
  const grading = dataset.scoring.judge.enabled || dataset.scoring.reference.enabled;

  return (
    <div className="space-y-2 py-2">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          aria-expanded={open}
          aria-label={t("judgeDatasetOpen", { name: dataset.name })}
          onClick={() => setOpen((was) => !was)}
        >
          <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
        </Button>
        <Link
          href={`${ROUTES.DATASET_DETAIL(dataset.id)}?tab=grading`}
          className="text-primary text-sm font-medium underline-offset-2 hover:underline"
        >
          {dataset.name}
        </Link>
        {!grading && <Badge variant="secondary">{t("judgeDatasetGradingOff")}</Badge>}
      </div>
      {open && (
        <div className="pl-8">
          <JudgeDatasetGrades datasetId={dataset.id} judgeId={judgeId} />
        </div>
      )}
    </div>
  );
}
