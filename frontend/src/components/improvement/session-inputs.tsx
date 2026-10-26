"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovementEvidence } from "@/hooks/use-improvements";
import { GenerateCasesDialog } from "@/components/datasets/generate-cases-dialog";
import { useDataset, useDatasetCases } from "@/hooks/use-datasets";
import { useEvalRun, useEvalCases } from "@/hooks/use-eval-runs";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement } from "@/types/improvement";
import type { DatasetCase } from "@/types/datasets";

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
    <section className="space-y-3" aria-label={t("sourceSignals")}>
      <p className="text-muted-foreground text-sm">{t("signalWindow")}</p>
      {attention.error || sources.error ? (
        <p role="alert">{getErrorMessage(attention.error || sources.error, tErrors)}</p>
      ) : attention.isLoading || sources.isLoading || !evidence ? (
        <p role="status">{t("loading")}</p>
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-3">
            {[
              [t("ratedSignals"), counts?.rated_down ?? 0],
              [t("failedSignals"), counts?.failed_runs ?? 0],
              [t("trainSignals"), evidence.training_failures],
            ].map(([label, count]) => (
              <div key={label} className="rounded-xl border p-4">
                <dt className="text-muted-foreground text-sm">{label}</dt>
                <dd className="mt-1 text-2xl font-medium tabular-nums">{count}</dd>
              </div>
            ))}
          </dl>
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

/** Below this, one question changing outcome swings the result too far to read it as a change. */
const MEASURABLE_QUESTIONS = 3;
const MORE_QUESTIONS = 5;

export function TestQuestions({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const [skip, setSkip] = useState(0);
  const [writing, setWriting] = useState(false);
  const { dataset } = useDataset(session.dataset_id);
  const questions = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    skip,
    limit: 20,
  });
  const all = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    limit: SOURCE_LIMIT,
  });
  if (questions.error) return <p role="alert">{getErrorMessage(questions.error, tErrors)}</p>;
  if (questions.isLoading) return <p role="status">{t("loading")}</p>;
  return (
    <section className="space-y-4" data-tour="improvement-test-questions">
      <h2 className="font-medium">
        {all.cases.length === questions.total && questions.total > 0
          ? t("questionSources", { count: questions.total, ...sourceCounts(all.cases) })
          : t("questionCount", { count: questions.total })}
      </h2>
      <p className="text-muted-foreground text-sm">{t("pinnedQuestions")}</p>
      {questions.total < MEASURABLE_QUESTIONS && (
        <div className="space-y-3 rounded-lg border p-3 text-sm">
          <p>{t("tooFewQuestions")}</p>
          {dataset?.can_edit && (
            <Button variant="outline" size="sm" onClick={() => setWriting(true)}>
              {t("writeMoreQuestions", { count: MORE_QUESTIONS })}
            </Button>
          )}
        </div>
      )}
      {writing && (
        <GenerateCasesDialog
          datasetId={session.dataset_id}
          open
          onOpenChange={setWriting}
          initial={{ agentId: session.agent_id, count: MORE_QUESTIONS }}
        />
      )}
      <details className="rounded-xl border p-4">
        <summary className="cursor-pointer text-sm font-medium">{t("reviewQuestions")}</summary>
        <ul className="mt-3 divide-y">
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
        <div className="mt-3 flex flex-wrap gap-2">
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
      </details>
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
  const tErrors = useTranslations("errors");
  const { run, error } = useEvalRun(runId);
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  const arm = run?.arms.find((item) => item.role === "baseline");
  if (!run || run.status === "queued" || run.status === "running")
    return <p role="status">{t("baselinePending")}</p>;
  if (run.status !== "completed" || !arm) return <p role="alert">{t("baselineUnavailable")}</p>;
  return (
    <>
      <p className="text-lg font-medium">
        {t("baselineHandled", { passed: arm.summary.passed, total: arm.summary.cases })}
      </p>
      {arm.summary.incomplete + arm.summary.ungraded > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("baselineUndecided", { count: arm.summary.incomplete + arm.summary.ungraded })}
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
  const tErrors = useTranslations("errors");
  const questions = useEvalCases(runId, { arm: armId, outcome: "failed", limit: 20 });
  if (questions.error) return <p role="alert">{getErrorMessage(questions.error, tErrors)}</p>;
  if (questions.isLoading) return <p role="status">{t("loading")}</p>;
  return (
    <div className="space-y-3">
      {questions.cases.length ? (
        questions.cases.map((item) => {
          const attempt = item.attempts.find((a) => a.arm_id === armId && a.attempt === 0);
          return (
            <article key={item.case_id} className="space-y-2 rounded-xl border p-4 text-sm">
              <p className="font-medium break-words">{item.input}</p>
              <p className="break-words whitespace-pre-wrap">
                {attempt?.answer || t("unavailableAnswer")}
              </p>
              {attempt?.score?.results.map((grade, index) => (
                <p key={index} className="text-muted-foreground break-words">
                  {t("graderSaid", { reason: grade.reason })}
                </p>
              ))}
            </article>
          );
        })
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
