"use client";

import Link from "next/link";
import { GitCompare, ListFilter, RotateCcw, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button, Card, CardContent, Progress } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalComparison, EvalRun, EvalRunArm } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { EvalStatusBadge } from "./eval-status-badge";
import { usd } from "./format";
import { sideName } from "./names";
import { SendToReviewButton } from "./send-to-review-button";
import { JudgeNotes } from "./judge-notes";
import { UngradedNote } from "./ungraded-note";
import { VerdictBadge, VerdictHeadline } from "./verdict-headline";

/**
 * The top of a run's page: what was run, then - once both sides have finished -
 * the verdict in a sentence and what to do about it. While the run answers it
 * says how far it got and that the comparison waits for both sides.
 */
export function VerdictHeader({
  agentId,
  run,
  candidate,
  comparison,
  onCancel,
  onShowBroken,
  onTestAgain,
  onRetryComparison,
}: {
  agentId: string;
  run: EvalRun;
  /** The candidate the verdict is about - the first, or the model picked. */
  candidate: EvalRunArm | undefined;
  comparison: EvalComparison | undefined;
  onCancel?: () => void;
  onShowBroken: () => void;
  /** Test the draft as it stands now, for a run of a draft that has moved on - for who may. */
  onTestAgain?: () => void;
  /** Read the verdict again, when reading it failed. */
  onRetryComparison?: () => void;
}) {
  const t = useTranslations("evals");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { can } = usePermissions();
  const live = run.status === "queued" || run.status === "running";
  const reruns = run.attempts_total - run.first_total;
  const confirming = run.first_total > 0 && run.first_done === run.first_total && reruns > 0;
  const [doneNow, ofNow] = confirming
    ? [run.attempts_done - run.first_done, reruns]
    : [run.first_done, run.first_total];
  const done = ofNow === 0 ? 0 : (doneNow / ofNow) * 100;
  const broke = comparison
    ? comparison.regressions_confirmed + comparison.regressions_unconfirmed
    : 0;
  const brokeOnce = comparison !== undefined && comparison.regressions_unconfirmed > 0;
  const baseline = comparison?.baseline ?? null;
  return (
    <Card data-tour="eval-verdict">
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm">
              {t("runTitle", {
                dataset: run.dataset_name,
                version: run.dataset_version,
                candidate: candidate ? sideName(candidate, t) : "",
              })}
            </p>
            {!live && candidate && comparison && (
              <>
                <VerdictBadge comparison={comparison} />
                <h1 className="space-y-1 text-lg font-semibold">
                  <VerdictHeadline run={run} candidate={candidate} comparison={comparison} />
                </h1>
              </>
            )}
            {onRetryComparison && (
              <p role="alert" className="text-warning flex flex-wrap items-center gap-2 text-sm">
                {t("comparisonFailed")}
                <Button size="sm" variant="outline" onClick={onRetryComparison}>
                  {tc("retry")}
                </Button>
              </p>
            )}
            {comparison?.invalid_reason && (
              <p className="text-muted-foreground text-sm">{comparison.invalid_reason}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <EvalStatusBadge status={run.status} />
            {onCancel && (
              <Button size="sm" variant="outline" onClick={onCancel}>
                <Square className="h-3.5 w-3.5" aria-hidden />
                {t("cancelRun")}
              </Button>
            )}
          </div>
        </div>

        {live ? (
          <div className="space-y-2">
            <Progress value={done} aria-label={t("progress")} />
            <p className="text-muted-foreground text-xs">
              {confirming
                ? t("live.confirming", { done: doneNow, total: ofNow })
                : t("live.answering", { done: doneNow, total: ofNow })}
            </p>
            <p className="text-muted-foreground text-xs">{t("live.comparisonLater")}</p>
          </div>
        ) : (
          <p className="text-muted-foreground text-xs">
            {t("answers", { cases: run.cases, first: run.first_total, reruns })}
          </p>
        )}
        <p className="text-muted-foreground text-xs">
          {t("runMeta", {
            date: formatDateTime(run.created_at, locale),
            cost: usd(run.cost_usd, locale),
            estimate: usd(run.estimate_usd, locale),
            ceiling:
              Number(run.rerun_ceiling_usd) > 0 ? usd(run.rerun_ceiling_usd, locale) : "none",
          })}
        </p>
        {run.error && <p className="text-destructive text-sm">{run.error}</p>}
        {!live && <UngradedNote run={run} />}
        {!live && <JudgeNotes run={run} />}

        {!live && candidate && (
          <div className="flex flex-wrap gap-2">
            {baseline !== null &&
              baseline.version_number !== null &&
              candidate.version_number !== baseline.version_number && (
                <Button size="sm" variant="outline" asChild>
                  <Link
                    href={`${ROUTES.AGENTS}/${agentId}?tab=history&from=${baseline.version_number}&${
                      candidate.version_number === null
                        ? `run=${run.id}&arm=${candidate.id}`
                        : `to=${candidate.version_number}`
                    }`}
                  >
                    <GitCompare className="h-3.5 w-3.5" aria-hidden />
                    {t("actions.whatChanged")}
                  </Link>
                </Button>
              )}
            {broke > 0 && (
              <Button size="sm" variant="outline" onClick={onShowBroken}>
                <ListFilter className="h-3.5 w-3.5" aria-hidden />
                {brokeOnce
                  ? t("actions.showBrokenOnce", { count: broke })
                  : t("actions.showBroken", { count: broke })}
              </Button>
            )}
            <Button size="sm" variant="outline" asChild>
              <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build`}>{t("actions.backToBuild")}</Link>
            </Button>
            <SendToReviewButton run={run} arm={candidate} />
            {run.draft_changed && (
              <span className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">{t("draftChanged")}</span>
                {onTestAgain && (
                  <Button size="sm" onClick={onTestAgain}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                    {t("actions.testAgain")}
                  </Button>
                )}
              </span>
            )}
            {candidate.source === "draft" && !run.draft_changed && can(Perm.agentsPublish) && (
              <Button
                size="sm"
                variant={
                  comparison &&
                  comparison.regressions_confirmed === 0 &&
                  comparison.overall !== "worse" &&
                  candidate.summary.incomplete === 0 &&
                  candidate.ungraded_cases.length === 0
                    ? "default"
                    : "outline"
                }
                asChild
              >
                <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build&publish=1`}>
                  {t("actions.publish")}
                </Link>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
