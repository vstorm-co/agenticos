"use client";
import { type ReactNode, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { ImprovementMeasurement } from "@/components/evals/improvement-measurement";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import { ChangedAnswers } from "./changed-answers";
import { BeforeAfter, Details, StateBadge } from "./widgets";
import { useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalComparison } from "@/types/eval-runs";
import type { AttributionEstimate, Improvement, ImprovementIteration } from "@/types/improvement";
import { useReadOnly } from "./read-only";

export function RoundResults({
  session,
  round,
  extra,
}: {
  session: Improvement;
  round: ImprovementIteration;
  /** More sections for the attempt's Show details, kept to one place to open. */
  extra?: ReactNode;
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
  const selectable = !useReadOnly() && ["ready", "stopped"].includes(session.status);
  const latestCheck = round.eval_run_ids.at(-1);
  const fixed = round.verdict_detail?.fixed;
  const broken = round.verdict_detail?.broken;
  const countsKnown =
    fixed !== undefined && fixed !== null && broken !== undefined && broken !== null;
  const worse = round.verdict === "regression" && countsKnown && Number(fixed) === 0;
  const earlier = [...round.eval_run_ids.slice(0, -1), ...(round.previous_eval_run_ids ?? [])];
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-medium">
          <RoundTitle session={session} round={round} />
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
      <Details summary={t("showDetails")}>
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
        {latestCheck && <MeasurementSection runId={latestCheck} />}
        {earlier.length > 0 && (
          <section className="space-y-2">
            <h4 className="text-sm font-medium">{t("earlierChecks")}</h4>
            {earlier.map((id, index) => (
              <Link
                key={id}
                className="block text-sm underline underline-offset-4"
                href={`/agents/${session.agent_id}/evals/${id}`}
              >
                {t("earlierCheck", { number: index + 1 })}
              </Link>
            ))}
          </section>
        )}
        {selectable &&
          round.verdict &&
          Object.keys(round.attribution_eval_run_ids).length === 0 && (
            <section className="space-y-3">
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
            </section>
          )}
        {Object.entries(round.attribution_eval_run_ids).map(([hunkId, runId], index) => (
          <section key={hunkId} className="space-y-2">
            <h4 className="text-sm font-medium">{t("changeAttribution", { number: index + 1 })}</h4>
            <AttributionResult runId={runId} agentId={session.agent_id} />
          </section>
        ))}
        {extra}
      </Details>
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
      {comparison && <ChangeCounts comparison={comparison} />}
      {comparison && <AnswerCost comparison={comparison} changed />}
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
/** The attempt's measurement and, when it did not move, the cost per answer, for Show details. */
function MeasurementSection({ runId }: { runId: string }) {
  const t = useTranslations("improvement");
  const { run } = useEvalRun(runId);
  const { comparison } = useEvalComparison(runId);
  const measurement = run?.status === "completed" ? run.proposal_check?.measurement : undefined;
  if (!measurement && !comparison) return null;
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{t("measurementDetails")}</h4>
      {comparison && <AnswerCost comparison={comparison} changed={false} />}
      {measurement && <ImprovementMeasurement measurement={measurement} wizard />}
    </section>
  );
}

function perAnswer(summary: { cost_usd: string; cases: number }, locale: string) {
  return usd(String(Number(summary.cost_usd) / Math.max(1, summary.cases)), locale);
}

/**
 * The cost per answer before and after. On the result only when it moved;
 * otherwise in Show details, where `changed` is false.
 */
function AnswerCost({ comparison, changed }: { comparison: EvalComparison; changed: boolean }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  if (!comparison.baseline_summary) return null;
  const before = perAnswer(comparison.baseline_summary, locale);
  const after = perAnswer(comparison.candidate_summary, locale);
  if ((before !== after) !== changed) return null;
  return <p className="text-muted-foreground text-sm">{t("answerCost", { before, after })}</p>;
}

/**
 * Why the bars and the counts above them differ: the bars count every answer handled
 * well, and only a change asking again confirmed counts as newly fixed or broken.
 */
function ChangeCounts({ comparison }: { comparison: EvalComparison }) {
  const t = useTranslations("improvement");
  const flips = comparison.cases.filter((c) => c.flip === "fixed" || c.flip === "regression");
  if (flips.length === 0) return null;
  const confirmed = (flip: "fixed" | "regression") =>
    flips.filter((c) => c.confirmed && c.flip === flip).length;
  return (
    <p className="text-muted-foreground text-sm">
      {t("numbersExplained", {
        fixed: confirmed("fixed"),
        broken: confirmed("regression"),
        pending: flips.filter((c) => !c.confirmed).length,
      })}
    </p>
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
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded-xl border p-4"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-medium">
        <RoundTitle session={session} round={round} />
      </summary>
      {open && (
        <div className="mt-4">
          <RoundResults session={session} round={round} />
        </div>
      )}
    </details>
  );
}

/**
 * A round's name. One past the attempt limit was set aside by an earlier round
 * for an attempt that never came, so it is named for that rather than counted.
 */
export function RoundTitle({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement");
  return round.number > session.max_iterations
    ? t("heldBack")
    : t("round", { number: round.number, max: session.max_iterations });
}
