"use client";

import Link from "next/link";
import { GitCompare, ListFilter, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button, Card, CardContent, Progress } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalComparison, EvalRun, EvalRunArm, Verdict } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { EvalStatusBadge } from "./eval-status-badge";
import { percent, usd } from "./format";
import { sideName } from "./names";
import { SendToReviewButton } from "./send-to-review-button";

export const VERDICT_TONE: Record<Verdict, "success" | "destructive" | "secondary" | "warning"> = {
  better: "success",
  worse: "destructive",
  no_difference: "secondary",
  inconclusive: "secondary",
  invalid: "warning",
};

/** The verdict as a sentence a person reads first: who did better, by how much, on what. */
function Headline({
  run,
  candidate,
  comparison,
}: {
  run: EvalRun;
  candidate: EvalRunArm;
  comparison: EvalComparison;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const { baseline, verdict } = comparison;
  const values = {
    candidate: sideName(candidate, t),
    dataset: run.dataset_name,
    to: percent(comparison.candidate_summary.pass_rate, locale),
  };
  if (baseline === null || verdict === null) {
    return <>{t("headline.first", { ...values, rate: values.to })}</>;
  }
  const changes =
    comparison.regressions_confirmed +
    comparison.regressions_unconfirmed +
    comparison.fixed_confirmed +
    comparison.fixed_unconfirmed;
  return (
    <>
      {t(`headline.${verdict}`, {
        ...values,
        baseline: sideName(baseline, t),
        from: percent(comparison.baseline_summary?.pass_rate ?? null, locale),
        broke: comparison.regressions_confirmed,
        fixed: comparison.fixed_confirmed,
        changes,
      })}
    </>
  );
}

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
}: {
  agentId: string;
  run: EvalRun;
  /** The candidate the verdict is about - the first, or the model picked. */
  candidate: EvalRunArm | undefined;
  comparison: EvalComparison | undefined;
  onCancel?: () => void;
  onShowBroken: () => void;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const { can } = usePermissions();
  const live = run.status === "queued" || run.status === "running";
  const done = run.first_total === 0 ? 0 : (run.first_done / run.first_total) * 100;
  const broke = comparison
    ? comparison.regressions_confirmed + comparison.regressions_unconfirmed
    : 0;
  const baseline = comparison?.baseline ?? null;
  const reruns = run.attempts_total - run.first_total;
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
              <h1 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                {comparison.verdict && (
                  <Badge variant={VERDICT_TONE[comparison.verdict]}>
                    {t(`comparison.verdict.${comparison.verdict}`)}
                  </Badge>
                )}
                <Headline run={run} candidate={candidate} comparison={comparison} />
              </h1>
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
              {t("live.answering", { done: run.first_done, total: run.first_total })}
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

        {!live && candidate && (
          <div className="flex flex-wrap gap-2">
            {baseline !== null &&
              baseline.version_number !== null &&
              candidate.version_number !== baseline.version_number && (
                <Button size="sm" variant="outline" asChild>
                  <Link
                    href={`${ROUTES.AGENTS}/${agentId}?tab=history&from=${baseline.version_number}&to=${candidate.version_number ?? "draft"}`}
                  >
                    <GitCompare className="h-3.5 w-3.5" aria-hidden />
                    {t("actions.whatChanged")}
                  </Link>
                </Button>
              )}
            {broke > 0 && (
              <Button size="sm" variant="outline" onClick={onShowBroken}>
                <ListFilter className="h-3.5 w-3.5" aria-hidden />
                {t("actions.showBroken", { count: broke })}
              </Button>
            )}
            <Button size="sm" variant="outline" asChild>
              <Link href={`${ROUTES.AGENTS}/${agentId}?tab=build`}>{t("actions.backToBuild")}</Link>
            </Button>
            <SendToReviewButton run={run} arm={candidate} />
            {candidate.source === "draft" && can(Perm.agentsPublish) && (
              <Button
                size="sm"
                variant={
                  comparison &&
                  comparison.regressions_confirmed === 0 &&
                  comparison.verdict !== "worse"
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
