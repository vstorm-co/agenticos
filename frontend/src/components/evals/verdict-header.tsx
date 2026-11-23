"use client";

import Link from "next/link";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { GitCompare, ListFilter, RotateCcw, Settings2, Square, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { DatasetIcon } from "@/components/datasets/dataset-chip";
import { cn } from "@/lib/utils";
import { Badge, Button, Card, CardContent, Progress } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalComparison, EvalRun, EvalRunArm } from "@/types/eval-runs";
import { SuiteCheckVerdict } from "./suite-check-verdict";
import { EvalStatusBadge } from "./eval-status-badge";
import { ResultOverview } from "./result-overview";
import { sideName } from "./names";
import { percent, usd } from "./format";
import { SendToReviewButton } from "./send-to-review-button";
import { JudgeNotes } from "./judge-notes";
import { UngradedNote } from "./ungraded-note";
import { undecidedOf, VerdictBadge, VerdictHeadline } from "./verdict-headline";

/** The check of a skill change that a run is one stage of, as the page names it. */
export interface CheckStage {
  skillId: string;
  /** Null until the skill is read, or for a reader who may not see it. */
  skillName: string | null;
  agent: string;
  checkId: string;
}

/**
 * The top of a run's page: what was run, then - once both sides have finished -
 * the verdict in a sentence and what to do about it. While the run answers it
 * says how far it got and that the comparison waits for both sides. A stage of a
 * skill's check says so and links the check, which owns its price and its verdict,
 * so the stage's own estimate and the way back to Build are left out.
 */
export function VerdictHeader({
  agentId,
  run,
  candidate,
  canPublish,
  canEditDataset,
  comparison,
  onCancel,
  onShowBroken,
  onShowFailed,
  onTestAgain,
  onRetryComparison,
  stage = null,
}: {
  agentId: string;
  run: EvalRun;
  /** The candidate the verdict is about - the first, or the model picked. */
  candidate: EvalRunArm | undefined;
  /** Whether the caller may publish this agent - the role's publish and an edit on it. */
  canPublish: boolean;
  canEditDataset: boolean;
  comparison: EvalComparison | undefined;
  onCancel?: () => void;
  onShowBroken: () => void;
  onShowFailed?: () => void;
  /** Test the draft as it stands now, for a run of a draft that has moved on - for who may. */
  onTestAgain?: () => void;
  /** Read the verdict again, when reading it failed. */
  onRetryComparison?: () => void;
  stage?: CheckStage | null;
}) {
  const t = useTranslations("evals");
  const tc = useTranslations("common");
  const journey = useTranslations("datasets.journey");
  const locale = useLocale();
  const live = run.status === "queued" || run.status === "running";
  const reruns = run.attempts_total - run.first_total;
  const compares = run.paired || comparison?.baseline != null;
  const confirming = run.first_total > 0 && run.first_done === run.first_total && reruns > 0;
  const [doneNow, ofNow] = confirming
    ? [run.attempts_done - run.first_done, reruns]
    : [run.first_done, run.first_total];
  const done = ofNow === 0 ? 0 : (doneNow / ofNow) * 100;
  const broke =
    comparison && comparison.verdict !== "invalid"
      ? comparison.regressions_confirmed + comparison.regressions_unconfirmed
      : 0;
  const brokeOnce = comparison !== undefined && comparison.regressions_unconfirmed > 0;
  const baseline = comparison?.baseline ?? null;
  const undecided = candidate ? undecidedOf(candidate) : 0;
  const setupFailed = !live && candidate?.failed_alike != null;
  return (
    <Card data-tour="eval-verdict" className={cn(setupFailed && "border-destructive/25")}>
      <CardContent className="space-y-3 p-4 sm:p-5">
        {!live && candidate && comparison && !setupFailed && (
          <ResultOverview comparison={comparison} candidate={candidate} />
        )}
        {!live &&
          onShowFailed &&
          candidate &&
          candidate.summary.failed > 0 &&
          !setupFailed &&
          !run.draft_changed && (
            <Button size="sm" onClick={onShowFailed}>
              {t("resultFailed", { count: candidate.summary.failed })}
            </Button>
          )}
        {!live &&
          candidate &&
          candidate.summary.failed === 0 &&
          candidate.summary.ungraded > 0 &&
          canEditDataset && (
            <Button size="sm" asChild>
              <Link href={`${ROUTES.DATASET_DETAIL(run.dataset_id)}?tab=settings`}>
                {journey("next.grading")}
              </Link>
            </Button>
          )}
        {!live &&
          candidate?.source === "draft" &&
          candidate.summary.failed === 0 &&
          undecided === 0 &&
          canPublish &&
          !setupFailed &&
          !run.draft_changed &&
          comparison &&
          comparison.verdict !== "invalid" &&
          comparison.overall !== "worse" && (
            <Button size="sm" asChild>
              <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build`}>{t("plain.reviewChanges")}</Link>
            </Button>
          )}
        {run.draft_changed && <p className="text-warning-ink text-sm">{t("draftChanged")}</p>}
        {(run.draft_changed || setupFailed) && onTestAgain && (
          <Button size="sm" onClick={onTestAgain}>
            <RotateCcw className="size-4" aria-hidden />
            {t("actions.testAgain")}
          </Button>
        )}
        <NativeDisclosure
          open={
            live || setupFailed || Boolean(run.error) || Boolean(onRetryComparison)
              ? true
              : undefined
          }
          className="text-sm"
        >
          <summary className="text-muted-foreground cursor-pointer">{t("plain.details")}</summary>
          <div className="space-y-4 pt-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1 space-y-3 break-words">
                {stage && (
                  <p className="text-sm font-medium">
                    {t.rich("checkStage.title", {
                      skill: stage.skillName ?? t("checkStage.aSkill"),
                      agent: stage.agent,
                      check: (chunks) => (
                        <Link
                          className="underline underline-offset-4"
                          href={`${ROUTES.SKILL_DETAIL(stage.skillId)}?tab=history&check=${stage.checkId}`}
                        >
                          {chunks}
                        </Link>
                      ),
                    })}
                  </p>
                )}
                {!live && candidate && comparison && candidate.failed_alike !== null && (
                  <div className="flex items-start gap-4">
                    <DatasetIcon tone="red" icon={TriangleAlert} className="size-10" />
                    <div className="min-w-0 flex-1 space-y-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <h2 className="text-base font-semibold">{t("executionFailure.title")}</h2>
                        <Badge variant="destructive">{t("comparison.verdict.failedAlike")}</Badge>
                      </div>
                      <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
                        {t("executionFailure.body")}
                      </p>
                      <div
                        role="alert"
                        className="bg-destructive/5 text-destructive-ink border-destructive/15 max-w-4xl rounded-lg border px-4 py-3 text-sm leading-relaxed break-words"
                      >
                        {candidate.failed_alike}
                      </div>
                    </div>
                  </div>
                )}
                {!live && candidate && comparison && candidate.failed_alike === null && (
                  <>
                    <p className="text-muted-foreground text-xs">
                      {baseline
                        ? t("resultSides", {
                            candidate: t("sideModel", {
                              name: sideName(candidate, t, run.proposal_check),
                              model: candidate.model_label,
                            }),
                            baseline: t("sideModel", {
                              name: sideName(baseline, t, run.proposal_check),
                              model: baseline.model_label,
                            }),
                          })
                        : t("sideModel", {
                            name: sideName(candidate, t, run.proposal_check),
                            model: candidate.model_label,
                          })}
                    </p>
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                      <div>
                        <p className="text-muted-foreground text-xs">{t("arms.passRate")}</p>
                        <p className="text-3xl font-semibold tracking-tight tabular-nums">
                          {comparison.baseline && (
                            <span className="text-muted-foreground font-normal">
                              {percent(comparison.baseline_summary?.pass_rate ?? null, locale)}{" "}
                              →{" "}
                            </span>
                          )}
                          {percent(comparison.candidate_summary.pass_rate, locale)}
                        </p>
                      </div>
                      <VerdictBadge comparison={comparison} undecided={undecided} />
                    </div>
                    {comparison.baseline && comparison.verdict !== "invalid" && (
                      <p className="text-sm font-medium">
                        {t("resultSummary", {
                          fixed: comparison.fixed_confirmed,
                          broken: comparison.regressions_confirmed,
                        })}
                      </p>
                    )}
                    <NativeDisclosure
                      open={comparison.verdict === "invalid" || undecided > 0 ? true : undefined}
                      className="max-w-3xl text-sm"
                    >
                      <summary className="text-muted-foreground cursor-pointer">
                        {t("resultTabs.methodology")}
                      </summary>
                      <div className="space-y-2 pt-3 leading-relaxed">
                        <VerdictHeadline run={run} candidate={candidate} comparison={comparison} />
                      </div>
                    </NativeDisclosure>
                  </>
                )}
                {onRetryComparison && (
                  <p
                    role="alert"
                    className="text-warning-ink flex flex-wrap items-center gap-2 text-sm"
                  >
                    {t("comparisonFailed")}
                    <Button size="sm" variant="outline" onClick={onRetryComparison}>
                      {tc("retry")}
                    </Button>
                  </p>
                )}
                {comparison?.invalid_reason &&
                  !(stage && comparison.invalid_reason_code === "too_few_held_out") && (
                    <p className="text-muted-foreground text-sm">{comparison.invalid_reason}</p>
                  )}
                {comparison !== undefined && comparison.changed > 0 && (
                  <p className="text-muted-foreground text-sm">
                    {t("changedSinceBaseline", { count: comparison.changed })}
                  </p>
                )}
                {comparison?.baseline && !comparison.baseline_rerun && (
                  <p className="text-muted-foreground text-sm">{t("baselineNotRerun")}</p>
                )}
              </div>
              <div className="order-first flex items-center justify-end gap-2 sm:order-last">
                {!setupFailed && <EvalStatusBadge status={run.status} />}
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
                    : t(compares ? "live.answering" : "live.answeringSingle", {
                        done: doneNow,
                        total: ofNow,
                      })}
                </p>
                {compares && (
                  <p className="text-muted-foreground text-xs">{t("live.comparisonLater")}</p>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">
                {setupFailed
                  ? t("executionFailure.attempts", { count: run.cases })
                  : t("answers", { cases: run.cases, first: run.first_total, reruns })}
              </p>
            )}
            <p className="text-muted-foreground text-xs">
              {stage
                ? t("runMetaStage", {
                    date: formatDateTime(run.created_at, locale),
                    cost: usd(run.cost_usd, locale),
                  })
                : t("runMeta", {
                    date: formatDateTime(run.created_at, locale),
                    cost: usd(run.cost_usd, locale),
                    estimate: usd(run.expected_usd, locale),
                    ceiling:
                      compares && Number(run.rerun_ceiling_usd) > 0
                        ? usd(
                            String(Number(run.estimate_usd) + Number(run.rerun_ceiling_usd)),
                            locale,
                          )
                        : "none",
                  })}
            </p>
            {run.suite && (
              <p className="text-muted-foreground text-xs">
                {t("startedBySuite", { name: run.suite.name, trigger: run.suite.trigger })}
              </p>
            )}
            {run.suite_check && <SuiteCheckVerdict agentId={agentId} check={run.suite_check} />}
            {run.error && <p className="text-destructive-ink text-sm">{run.error}</p>}
            {!live && <UngradedNote run={run} />}
            {!live && <JudgeNotes run={run} />}
          </div>
        </NativeDisclosure>
        {!live && candidate && (
          <NativeDisclosure className="text-sm">
            <summary className="text-muted-foreground cursor-pointer">{t("plain.actions")}</summary>
            <div className="flex flex-wrap gap-2 pt-3">
              {candidate.summary.ungraded > 0 && candidate.summary.failed > 0 && canEditDataset && (
                <Button size="sm" asChild>
                  <Link href={`${ROUTES.DATASET_DETAIL(run.dataset_id)}?tab=settings`}>
                    <Settings2 className="size-4" aria-hidden />
                    {journey("next.grading")}
                  </Link>
                </Button>
              )}
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
              {!stage && (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build`}>
                    <Settings2 className="size-4" aria-hidden />
                    {t("actions.backToBuild")}
                  </Link>
                </Button>
              )}
              <SendToReviewButton run={run} arm={candidate} />
              {candidate.source === "draft" && !run.draft_changed && canPublish && (
                <Button
                  size="sm"
                  variant={
                    comparison &&
                    comparison.regressions_confirmed === 0 &&
                    comparison.overall !== "worse" &&
                    undecided === 0
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
          </NativeDisclosure>
        )}
      </CardContent>
    </Card>
  );
}
