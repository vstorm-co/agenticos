"use client";
import { useState } from "react";
import Link from "next/link";
import { Coins } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { ImprovementMeasurement } from "@/components/evals/improvement-measurement";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import { ChangedAnswers } from "./changed-answers";
import { BeforeAfter, StateBadge } from "./widgets";
import { useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { AttributionEstimate, Improvement, ImprovementIteration } from "@/types/improvement";

export function RoundResults({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const [quote, setQuote] = useState<AttributionEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  const selectable = ["ready", "stopped"].includes(session.status);
  const latestCheck = round.eval_run_ids.at(-1);
  const fixed = round.verdict_detail?.fixed;
  const broken = round.verdict_detail?.broken;
  const countsKnown =
    fixed !== undefined && fixed !== null && broken !== undefined && broken !== null;
  const worse = round.verdict === "regression" && countsKnown && Number(fixed) === 0;
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-medium">
          {t("round", { number: round.number, max: session.max_iterations })}
        </h3>
        <span className="text-muted-foreground text-sm">{usd(round.cost_usd, locale)}</span>
      </div>
      <StateBadge
        className="text-sm"
        tone={
          round.verdict === "better"
            ? "good"
            : round.verdict === "regression"
              ? worse
                ? "bad"
                : "warn"
              : "neutral"
        }
      >
        {round.verdict
          ? countsKnown
            ? t(worse ? "worseResult" : `verdict.${round.verdict}`, {
                fixed: Number(fixed),
                broken: Number(broken),
              })
            : t("resultDetailsUnavailable")
          : t(
              ["queued", "running"].includes(session.status) ? "working" : "attributionUnavailable",
            )}
      </StateBadge>
      {latestCheck && (
        <MeasuredResult runId={latestCheck} attributions={round.attribution_eval_run_ids} />
      )}
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer text-sm font-medium">{t("showDetails")}</summary>
        <div className="mt-3 space-y-4">
          {round.id === session.best_iteration_id && (
            <p className="text-sm font-medium">{t("selected")}</p>
          )}
          {selectable &&
            round.verdict &&
            (round.id !== session.best_iteration_id || session.status === "stopped") && (
              <Button
                variant="outline"
                disabled={actions.selectRound.isPending}
                onClick={() =>
                  void act(async () => {
                    await actions.selectRound.mutateAsync(round.number);
                  })
                }
              >
                {t("selectRound")}
              </Button>
            )}
          {[...round.eval_run_ids.slice(0, -1), ...(round.previous_eval_run_ids ?? [])].length >
            0 && (
            <details className="rounded-lg border p-3">
              <summary className="cursor-pointer text-sm font-medium">{t("earlierChecks")}</summary>
              <div className="mt-3 space-y-2">
                {[...round.eval_run_ids.slice(0, -1), ...(round.previous_eval_run_ids ?? [])].map(
                  (id, index) => (
                    <Link
                      key={id}
                      className="block text-sm underline underline-offset-4"
                      href={`/agents/${session.agent_id}/evals/${id}`}
                    >
                      {t("earlierCheck", { number: index + 1 })}
                    </Link>
                  ),
                )}
              </div>
            </details>
          )}

          {selectable &&
            round.verdict &&
            Object.keys(round.attribution_eval_run_ids).length === 0 && (
              <div className="space-y-3 border-t pt-4">
                <p className="text-muted-foreground text-sm">{t("attributionBody")}</p>
                <Button
                  variant="outline"
                  disabled={actions.estimateAttribution.isPending}
                  onClick={() =>
                    void act(async () =>
                      setQuote(await actions.estimateAttribution.mutateAsync(round.number)),
                    )
                  }
                >
                  {t("estimateAttribution")}
                </Button>
                {quote && (
                  <>
                    <p className="text-sm">
                      {t("attributionQuote", {
                        count: quote.changes,
                        cost: usd(quote.total_usd, locale),
                      })}
                    </p>
                    <Button
                      disabled={!quote.affordable || actions.attribute.isPending}
                      onClick={() =>
                        void act(async () => {
                          await actions.attribute.mutateAsync({
                            number: round.number,
                            estimate: quote.total_usd,
                          });
                          setQuote(null);
                        })
                      }
                    >
                      {t("confirmAttribution")}
                    </Button>
                  </>
                )}
              </div>
            )}
          {Object.entries(round.attribution_eval_run_ids).map(([hunkId, runId], index) => (
            <details key={hunkId} className="rounded-lg border p-3">
              <summary className="cursor-pointer text-sm font-medium">
                {t("changeAttribution", { number: index + 1 })}
              </summary>
              <div className="mt-3">
                <AttributionResult runId={runId} agentId={session.agent_id} />
              </div>
            </details>
          ))}
        </div>
      </details>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}

function MeasuredResult({
  runId,
  attributions,
}: {
  runId: string;
  attributions: Record<string, string>;
}) {
  const { run, error } = useEvalRun(runId);
  const { comparison, error: comparisonError } = useEvalComparison(runId, {
    live: run?.status === "queued" || run?.status === "running",
  });
  const locale = useLocale();
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (!run) return <p role="status">{t("loading")}</p>;
  if (run.status !== "completed")
    return (
      <div className="space-y-2 text-sm">
        <p role={run.status === "queued" || run.status === "running" ? "status" : "alert"}>
          {t(
            run.status === "queued" || run.status === "running"
              ? "background"
              : "attributionUnavailable",
          )}
        </p>
        <Link
          className="underline underline-offset-4"
          href={`/agents/${run.agent_id}/evals/${runId}`}
        >
          {t("openCheck")}
        </Link>
      </div>
    );
  const baseline = run.arms.find((arm) => arm.role === "baseline");
  const candidate = run.arms.find((arm) => arm.role === "candidate");
  return (
    <div className="space-y-4">
      {run.review && <ReviewReevaluationNote review={run.review} />}
      {run.proposal_check?.measurement && (
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("measurementDetails")}
          </summary>
          <div className="mt-3">
            <ImprovementMeasurement measurement={run.proposal_check.measurement} wizard />
          </div>
        </details>
      )}
      {comparisonError && <p role="alert">{getErrorMessage(comparisonError, tErrors)}</p>}
      {!comparison && !comparisonError && <p role="status">{t("loading")}</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {baseline && candidate && (
          <BeforeAfter
            title={t("widgets.allQuestions")}
            label={t("handledChange", {
              before: baseline.summary.passed,
              after: candidate.summary.passed,
              total: candidate.summary.cases,
            })}
            before={baseline.summary.passed}
            after={candidate.summary.passed}
            total={candidate.summary.cases}
          />
        )}
        {comparison?.baseline_summary && (
          <BeforeAfter
            title={t("widgets.heldOut")}
            label={t("heldoutResult", {
              before: comparison.baseline_summary.passed,
              after: comparison.candidate_summary.passed,
              total: comparison.candidate_summary.cases,
            })}
            before={comparison.baseline_summary.passed}
            after={comparison.candidate_summary.passed}
            total={comparison.candidate_summary.cases}
          />
        )}
      </div>
      {comparison?.baseline_summary && (
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <Coins className="size-4 shrink-0" aria-hidden />
          {t("answerCost", {
            before: usd(
              String(
                Number(comparison.baseline_summary.cost_usd) /
                  Math.max(1, comparison.baseline_summary.cases),
              ),
              locale,
            ),
            after: usd(
              String(
                Number(comparison.candidate_summary.cost_usd) /
                  Math.max(1, comparison.candidate_summary.cases),
              ),
              locale,
            ),
          })}
        </p>
      )}
      {comparison &&
        (comparison.baseline &&
        comparison.cases.some((c) => c.flip === "regression" || c.flip === "fixed") ? (
          <ChangedAnswers
            runId={runId}
            agentId={run.agent_id}
            flips={comparison.cases.filter((c) => c.flip === "regression" || c.flip === "fixed")}
            baselineId={comparison.baseline.arm_id}
            candidateId={comparison.candidate.arm_id}
            attributions={attributions}
          />
        ) : (
          <div className="space-y-2">
            <p className="text-muted-foreground text-sm">{t("noChangedQuestions")}</p>
            <Link className="text-sm underline" href={`/agents/${run.agent_id}/evals/${runId}`}>
              {t("openCheck")}
            </Link>
          </div>
        ))}
    </div>
  );
}
function AttributionResult({ runId, agentId }: { runId: string; agentId: string }) {
  const { run, error } = useEvalRun(runId);
  const { comparison, error: comparisonError } = useEvalComparison(runId, {
    live: run?.status === "running" || run?.status === "queued",
  });
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  const confirmed =
    comparison?.cases.filter(
      (c) => c.confirmed && (c.flip === "regression" || c.flip === "fixed"),
    ) ?? [];
  const unavailable =
    comparisonError ||
    comparison?.verdict === "invalid" ||
    (run && !["queued", "running", "completed"].includes(run.status));
  return (
    <div className="space-y-2 text-sm">
      {unavailable ? (
        <p role="alert">{t("attributionUnavailable")}</p>
      ) : run?.status !== "completed" || !comparison ? (
        <p role="status">{t("working")}</p>
      ) : confirmed.length ? (
        confirmed.map((c) => (
          <p key={c.case_id}>
            {t(c.flip === "regression" ? "causedBreak" : "causedFix", { question: c.input })}
          </p>
        ))
      ) : (
        <p>{t("noChangedQuestions")}</p>
      )}
      <Link className="underline underline-offset-4" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}

export function RoundHistory({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement");
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded-xl border p-4"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-medium">
        {t("round", { number: round.number, max: session.max_iterations })}
      </summary>
      {open && (
        <div className="mt-4">
          <RoundResults session={session} round={round} />
        </div>
      )}
    </details>
  );
}
