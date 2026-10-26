"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ListX, ThumbsDown, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovementEvidence } from "@/hooks/use-improvements";
import { useDatasetCases } from "@/hooks/use-datasets";
import { useEvalRun, useEvalCases } from "@/hooks/use-eval-runs";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement } from "@/types/improvement";
import type { DatasetCase } from "@/types/datasets";
import { WriteQuestions } from "./write-questions";
import { StepError } from "./step-error";
import { Details, Handled, Proportion, StateBadge, Tiles } from "./widgets";

export function StartSignals({ agentId, datasetId }: { agentId: string; datasetId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const [period] = useState(() => {
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 29);
    return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
  });
  const attention = useAgentAttention(period);
  const sources = useImprovementEvidence(agentId, { datasetId: datasetId || null });
  const evidence = sources.evidence;
  const counts = attention.agents.find((agent) => agent.agent_id === agentId);
  return (
    <section className="space-y-2" aria-label={t("sourceSignals")}>
      {attention.error || sources.error ? (
        <p role="alert">{getErrorMessage(attention.error || sources.error, tErrors)}</p>
      ) : attention.isLoading || sources.isLoading || !evidence ? (
        <p role="status">{t("loading")}</p>
      ) : (
        <>
          <Tiles
            tiles={[
              {
                label: t("ratedSignals"),
                value: counts?.rated_down ?? 0,
                tone: "rose",
                icon: ThumbsDown,
              },
              {
                label: t("failedSignals"),
                value: counts?.failed_runs ?? 0,
                tone: "amber",
                icon: AlertTriangle,
              },
              {
                label: t("trainSignals"),
                value: evidence.training_failures,
                tone: "violet",
                icon: ListX,
              },
            ]}
          />
          <p className="text-muted-foreground text-xs">{t("signalWindow")}</p>
          {evidence.items.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("noLearningExamples")}</p>
          )}
        </>
      )}
    </section>
  );
}

const SOURCE_LIMIT = 100;

/** Rated answers become questions: a thumbs-down keeps the answer to avoid, a thumbs-up the good one. */
function sourceCounts(cases: DatasetCase[]) {
  const rated = cases.filter((item) => item.source === "conversation");
  const down = rated.filter((item) => item.counter_example !== null).length;
  const written = cases.filter((item) => item.source === "synthetic").length;
  return {
    down,
    liked: rated.length - down,
    written,
    other: cases.length - rated.length - written,
  };
}

const MORE_QUESTIONS = 5;

/**
 * How many more questions to write so the session has enough not used to write the
 * changes. The server's own count of what is missing decides it; a new question
 * lands on either side, so twice the shortfall is asked for.
 */
function questionsToWrite(session: Improvement): number {
  const missing = Number(session.iterations[0]?.verdict_detail?.missing_holdout ?? 0);
  return missing > 0 ? Math.max(MORE_QUESTIONS, missing * 2) : 0;
}

export function TestQuestions({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const [skip, setSkip] = useState(0);
  const [writtenTo, setWrittenTo] = useState<string | null>(null);
  const more = questionsToWrite(session);
  const questions = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    skip,
    limit: 20,
  });
  const all = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    limit: SOURCE_LIMIT,
  });
  if (questions.error) return <StepError error={questions.error} retry={questions.refetch} />;
  if (questions.isLoading) return <p role="status">{t("loading")}</p>;
  const whole = all.cases.length === questions.total && questions.total > 0;
  const sources = sourceCounts(all.cases);
  const train = all.cases.filter((item) => item.improvement_partition === "train").length;
  return (
    <section className="space-y-5" data-tour="improvement-test-questions">
      <h2 className="text-lg font-medium">{t("questionCount", { count: questions.total })}</h2>
      {whole && (
        <div className="grid gap-4 md:grid-cols-2">
          <figure className="space-y-3 rounded-xl border p-4">
            <figcaption className="text-sm font-medium">{t("widgets.whereFrom")}</figcaption>
            <Proportion
              label={t("questionSources", { count: questions.total, ...sources })}
              parts={[
                { label: t("widgets.fromRatedDown"), value: sources.down, fill: "var(--series-4)" },
                { label: t("widgets.fromLiked"), value: sources.liked, fill: "var(--series-2)" },
                { label: t("widgets.written"), value: sources.written, fill: "var(--series-1)" },
                { label: t("widgets.byHand"), value: sources.other, fill: "var(--series-5)" },
              ]}
            />
          </figure>
          <figure className="space-y-3 rounded-xl border p-4">
            <figcaption className="text-sm font-medium">{t("widgets.howUsed")}</figcaption>
            <Proportion
              label={t("widgets.partitionLabel", {
                train,
                holdout: all.cases.length - train,
              })}
              parts={[
                { label: t("widgets.helpWrite"), value: train, fill: "var(--series-3)" },
                {
                  label: t("widgets.keptAside"),
                  value: all.cases.length - train,
                  fill: "var(--color-chart)",
                },
              ]}
            />
          </figure>
        </div>
      )}
      <p className="text-muted-foreground text-sm">{t("pinnedQuestions")}</p>
      {more > 0 && (
        <div className="border-warning/35 bg-warning/5 space-y-3 rounded-xl border p-4 text-sm">
          <StateBadge tone="warn">{t("widgets.tooFew")}</StateBadge>
          <p>
            {t("tooFewHeldOut", {
              needed: Number(session.iterations[0]?.verdict_detail?.missing_holdout),
            })}
          </p>
          {writtenTo ? (
            <Link
              className="underline underline-offset-4"
              href={`/agents/${session.agent_id}/improve/new?dataset=${writtenTo}`}
            >
              {t("startWithNewQuestions")}
            </Link>
          ) : (
            <WriteQuestions agentId={session.agent_id} more={more} onReady={setWrittenTo} />
          )}
        </div>
      )}
      <Details summary={t("reviewQuestions")}>
        <ul className="divide-y">
          {questions.cases.map((item) => (
            <li key={item.id} className="space-y-2 py-3 text-sm">
              <p className="font-medium break-words">{item.input}</p>
              <p className="text-muted-foreground text-xs">
                {t(item.improvement_partition === "train" ? "trainQuestion" : "holdoutQuestion")}
              </p>
              {item.reference_answer && (
                <p className="break-words whitespace-pre-wrap">
                  {t("goodAnswer", { answer: item.reference_answer })}
                </p>
              )}
              {item.counter_example && (
                <p className="break-words whitespace-pre-wrap">
                  {t("answerToAvoid", { answer: item.counter_example })}
                </p>
              )}
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={skip === 0}
            onClick={() => setSkip(Math.max(0, skip - 20))}
          >
            {t("sourcePreviousQuestions")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={skip + 20 >= questions.total}
            onClick={() => setSkip(skip + 20)}
          >
            {t("sourceNextQuestions")}
          </Button>
        </div>
      </Details>
      <Link
        className="text-sm underline underline-offset-4"
        href={`/datasets/${session.dataset_id}`}
      >
        {t("editQuestions")}
      </Link>
    </section>
  );
}

export function Today({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const firstCheck = session.iterations[0]?.eval_run_ids.at(-1);
  return (
    <section className="space-y-4" data-tour="improvement-today">
      <h2 className="font-medium">{t("steps.today")}</h2>
      {firstCheck ? (
        <BaselineResult runId={firstCheck} />
      ) : (
        <p role="status" className="text-muted-foreground text-sm">
          {t("baselinePending")}
        </p>
      )}
    </section>
  );
}
function BaselineResult({ runId }: { runId: string }) {
  const t = useTranslations("improvement");
  const { run, error, refetch } = useEvalRun(runId);
  if (error) return <StepError error={error} retry={refetch} />;
  const arm = run?.arms.find((item) => item.role === "baseline");
  if (!run || run.status === "queued" || run.status === "running")
    return <p role="status">{t("baselinePending")}</p>;
  if (run.status !== "completed" || !arm) return <p role="alert">{t("baselineUnavailable")}</p>;
  const undecided = arm.summary.incomplete + arm.summary.ungraded;
  const handled = t("baselineHandled", { passed: arm.summary.passed, total: arm.summary.cases });
  return (
    <>
      <figure className="space-y-3 rounded-xl border p-4">
        <figcaption className="text-lg font-medium">{handled}</figcaption>
        <Handled
          label={handled}
          passed={arm.summary.passed}
          failed={Math.max(0, arm.summary.cases - arm.summary.passed - undecided)}
          undecided={undecided}
        />
      </figure>
      {undecided > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("baselineUndecided", { count: undecided })}
        </p>
      )}
      <BaselineQuestions runId={runId} agentId={run.agent_id} armId={arm.id} />
    </>
  );
}
function BaselineQuestions({
  runId,
  agentId,
  armId,
}: {
  runId: string;
  agentId: string;
  armId: string;
}) {
  const t = useTranslations("improvement");
  const questions = useEvalCases(runId, { arm: armId, outcome: "failed", limit: 20 });
  if (questions.error) return <StepError error={questions.error} retry={questions.refetch} />;
  if (questions.isLoading) return <p role="status">{t("loading")}</p>;
  return (
    <div className="space-y-3">
      {questions.cases.length ? (
        <>
          <h3 className="text-sm font-medium">{t("widgets.weakQuestions")}</h3>
          {questions.cases.map((item) => {
            const attempt = item.attempts.find((a) => a.arm_id === armId && a.attempt === 0);
            return (
              <Details
                key={item.case_id}
                summary={
                  <span className="inline-flex items-start gap-2">
                    <XCircle className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden />
                    <span className="break-words">{item.input}</span>
                  </span>
                }
              >
                <p className="text-sm break-words whitespace-pre-wrap">
                  {attempt?.answer || t("unavailableAnswer")}
                </p>
                {attempt?.score?.results.map((grade, index) => (
                  <p key={index} className="text-muted-foreground text-sm break-words">
                    {t("graderSaid", { reason: grade.reason })}
                  </p>
                ))}
              </Details>
            );
          })}
        </>
      ) : (
        <p className="text-muted-foreground text-sm">{t("noWeakQuestions")}</p>
      )}
      <Link
        className="text-sm underline underline-offset-4"
        href={`/agents/${agentId}/evals/${runId}`}
        data-tour="improvement-open-check"
      >
        {t("openCheck")}
      </Link>
    </div>
  );
}
