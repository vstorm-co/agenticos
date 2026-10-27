"use client";
import { type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import { ChangedAnswers } from "./changed-answers";
import { BeforeAfter, Details, StateBadge } from "./widgets";
import { useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalComparison } from "@/types/eval-runs";
import type {
  AttributionEstimate,
  Improvement,
  ImprovementIteration,
  MeasurementNoise,
} from "@/types/improvement";
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
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectable = !useReadOnly() && ["ready", "stopped"].includes(session.status);
  const latestCheck = round.eval_run_ids.at(-1);
  const earlier = [...round.eval_run_ids.slice(0, -1), ...(round.previous_eval_run_ids ?? [])];
  return (
    <section className="space-y-4">
      {latestCheck && (
        <MeasuredResult
          runId={latestCheck}
          attributions={round.attribution_eval_run_ids}
          noise={session.measurement_noise}
        />
      )}
      <Details summary={t("showDetails")} onToggle={setDetailsOpen}>
        {latestCheck && <HowMeasured runId={latestCheck} />}
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
        {detailsOpen &&
          selectable &&
          round.verdict &&
          Object.keys(round.attribution_eval_run_ids).length === 0 && (
            <WhichChangeHelped session={session} round={round} onError={setError} />
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
  noise,
}: {
  runId: string;
  attributions: Record<string, string>;
  noise?: MeasurementNoise | null;
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
  // Red or green only for a change asking again confirmed; anything else may be noise.
  const tone = (delta: number): "good" | "bad" | "neutral" =>
    delta > 0 && comparison?.fixed_confirmed
      ? "good"
      : delta < 0 && comparison?.regressions_confirmed
        ? "bad"
        : "neutral";
  const allDelta = baseline && candidate ? candidate.summary.passed - baseline.summary.passed : 0;
  const heldDelta = comparison?.baseline_summary
    ? comparison.candidate_summary.passed - comparison.baseline_summary.passed
    : 0;
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
            tone={tone(allDelta)}
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
            tone={tone(heldDelta)}
          />
        )}
      </div>
      {comparison && (
        <ChangeCounts comparison={comparison} deltas={[allDelta, heldDelta]} noise={noise} />
      )}
      {comparison && <AnswerCost comparison={comparison} />}
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
/** Which questions decided the attempt, as one sentence with their numbers. */
function HowMeasured({ runId }: { runId: string }) {
  const t = useTranslations("improvement.howMeasured");
  const { run } = useEvalRun(runId);
  const measurement = run?.status === "completed" ? run.proposal_check?.measurement : undefined;
  if (!measurement) return null;
  const train = measurement.train_case_ids.length;
  const heldOut = measurement.holdout_case_ids.length;
  const missing = Math.max(0, measurement.minimum_holdout - measurement.gradable_holdout);
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{t("title")}</h4>
      <p className="text-sm">{t("body", { total: train + heldOut, train, heldOut })}</p>
      {measurement.excluded_case_ids.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("excluded", { count: measurement.excluded_case_ids.length })}
        </p>
      )}
      {missing > 0 && (
        <p role="status" className="text-warning text-sm">
          {t("needed", { count: missing })}
        </p>
      )}
    </section>
  );
}

function perAnswer(summary: { cost_usd: string; cases: number }, locale: string) {
  return usd(String(Number(summary.cost_usd) / Math.max(1, summary.cases)), locale);
}

/** The cost per answer before and after, shown only when it moved. */
function AnswerCost({ comparison }: { comparison: EvalComparison }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  if (!comparison.baseline_summary) return null;
  const before = perAnswer(comparison.baseline_summary, locale);
  const after = perAnswer(comparison.candidate_summary, locale);
  if (before === after) return null;
  return <p className="text-muted-foreground text-sm">{t("answerCost", { before, after })}</p>;
}

/**
 * Why the bars and the fixed and broken counts differ, and when a difference
 * is too small, or the bars too contradictory, to mean anything.
 */
function ChangeCounts({
  comparison,
  deltas,
  noise,
}: {
  comparison: EvalComparison;
  deltas: [number, number];
  noise?: MeasurementNoise | null;
}) {
  const t = useTranslations("improvement");
  const flips = comparison.cases.filter((c) => c.flip === "fixed" || c.flip === "regression");
  const moved = deltas.filter((delta) => delta !== 0);
  const opposite = moved.some((delta) => delta > 0) && moved.some((delta) => delta < 0);
  const small = moved.length > 0 && moved.every((delta) => Math.abs(delta) === 1);
  const unconfirmed = comparison.fixed_confirmed + comparison.regressions_confirmed === 0;
  const withinNoise =
    unconfirmed && (opposite || small || (noise?.noisy === true && moved.length > 0));
  if (flips.length === 0 && !withinNoise) return null;
  return (
    <p className="text-muted-foreground text-sm">
      {flips.length > 0 &&
        t("barsExplained", { pending: flips.filter((c) => !c.confirmed).length })}
      {flips.length > 0 && withinNoise && " "}
      {withinNoise && t("withinNoise", { kind: small ? "one" : opposite ? "opposite" : "noisy" })}
    </p>
  );
}

/**
 * Testing each of an attempt's changes on its own, offered with its price, and
 * only when the attempt has more than one change to tell apart.
 */
function WhichChangeHelped({
  session,
  round,
  onError,
}: {
  session: Improvement;
  round: ImprovementIteration;
  onError: (message: string | null) => void;
}) {
  const t = useTranslations("improvement.eachChange");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const [quote, setQuote] = useState<AttributionEstimate | null>(null);
  const { mutateAsync: estimate } = actions.estimateAttribution;
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const value = await estimate(round.number);
        if (live) setQuote(value);
      } catch (reason) {
        if (live) onError(getErrorMessage(reason, tErrors));
      }
    })();
    return () => {
      live = false;
    };
  }, [estimate, round.number, onError, tErrors]);
  if (!quote || quote.changes < 2) return null;
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-medium">{t("title")}</h4>
      <p className="text-sm">
        {t("body", { count: quote.changes, cost: usd(quote.total_usd, locale) })}
      </p>
      {!quote.affordable && <p className="text-muted-foreground text-sm">{t("overLimit")}</p>}
      <Button
        variant="outline"
        disabled={!quote.affordable || actions.attribute.isPending}
        onClick={() =>
          void (async () => {
            onError(null);
            try {
              await actions.attribute.mutateAsync({
                number: round.number,
                estimate: quote.total_usd,
              });
              setQuote(null);
            } catch (reason) {
              onError(getErrorMessage(reason, tErrors));
            }
          })()
        }
      >
        {t("start")}
      </Button>
    </section>
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

/**
 * One attempt as a single row - its verdict, what it fixed and broke, the questions
 * kept aside before and after, and its cost - opening to the attempt's full result.
 */
export function AttemptRow({
  session,
  round,
  extra,
}: {
  session: Improvement;
  round: ImprovementIteration;
  extra?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details className="rounded-xl border" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm sm:px-4">
        <AttemptSummary session={session} round={round} />
      </summary>
      {open && (
        <div className="border-t p-3 sm:p-4">
          <RoundResults session={session} round={round} extra={extra} />
        </div>
      )}
    </details>
  );
}

/** An attempt in one line: its name, verdict, change against its own baseline, mark and cost. */
export function AttemptSummary({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const detail = round.verdict_detail;
  const fixed = detail?.fixed;
  const broken = detail?.broken;
  const heldOut = detail?.held_out;
  const verdict =
    round.verdict === "regression" && Number(fixed ?? 0) === 0 ? "worse" : round.verdict;
  return (
    <>
      <span className="font-medium">
        <RoundTitle session={session} round={round} />
      </span>
      <StateBadge
        tone={
          verdict === "better"
            ? "good"
            : verdict === "worse"
              ? "bad"
              : verdict === "regression"
                ? "warn"
                : "neutral"
        }
      >
        {t(
          `attempt.${
            verdict ??
            (["queued", "running"].includes(session.status)
              ? "working"
              : round.batch_id
                ? "unmeasured"
                : "none")
          }`,
        )}
      </StateBadge>
      {fixed != null && broken != null && (
        <span>
          {t("attempt.delta", {
            fixed: Number(fixed),
            broken: Number(broken),
            heldOut: heldOut == null ? "unknown" : Number(heldOut),
          })}
        </span>
      )}
      {round.id === session.best_iteration_id &&
        (round.verdict === "better" ? (
          <StateBadge tone="good">{t("attempt.best")}</StateBadge>
        ) : (
          personChose(session) && <StateBadge tone="neutral">{t("attempt.chosen")}</StateBadge>
        ))}
      <span className="text-muted-foreground ml-auto">{usd(round.cost_usd, locale)}</span>
    </>
  );
}

/**
 * Whether a person chose the kept attempt since the last verdict. Otherwise the
 * session kept it on its own, which says nothing for an attempt that was not better.
 */
function personChose(session: Improvement): boolean {
  const last = (action: string) =>
    session.timeline.filter((event) => event.action === action).at(-1)?.at;
  const chose = last("improvement.round_selected");
  const judged = last("improvement.verdict");
  return chose !== undefined && (judged === undefined || Date.parse(chose) > Date.parse(judged));
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
