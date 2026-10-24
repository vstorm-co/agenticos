"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovementEvidence } from "@/hooks/use-improvements";
import { useDatasetCases } from "@/hooks/use-datasets";
import { useEvalRun, useEvalCases } from "@/hooks/use-eval-runs";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementEvidenceItem } from "@/types/improvement";

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

export function Understand({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const sources = useImprovementEvidence(session.agent_id, {
    sessionId: session.id,
    live: session.status === "running" || session.status === "queued",
  });
  if (sources.error) return <p role="alert">{getErrorMessage(sources.error, tErrors)}</p>;
  if (sources.isLoading || !sources.evidence) return <p role="status">{t("loading")}</p>;
  const items = sources.evidence.items;
  return (
    <section className="space-y-4" data-tour="improvement-evidence">
      <h2 className="font-medium">{t("steps.understand")}</h2>
      <p className="text-muted-foreground text-sm">
        {t("evidenceSample", { count: items.length, limit: sources.evidence.sample_limit })}
      </p>
      {items.length === 0 && <p className="text-sm">{t("noLearningExamples")}</p>}
      {items.some((item) => item.branch === "unknown") && (
        <p className="rounded-lg border p-3 text-sm">{t("unknownCauses")}</p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(["agent", "missing_knowledge"] as const).map((branch) => {
          const selected = items.filter(
            (item) => item.branch === branch || (branch === "agent" && item.branch === "unknown"),
          );
          return (
            <section key={branch} className="min-w-0 space-y-3">
              <h3 className="text-sm font-medium">
                {t(`cause.${branch}`)}{" "}
                <span className="text-muted-foreground">({selected.length})</span>
              </h3>
              {selected.length ? (
                selected.map((item) => <EvidenceCard key={item.run_id} item={item} />)
              ) : (
                <p className="text-muted-foreground text-sm">{t("noExamplesInGroup")}</p>
              )}
            </section>
          );
        })}
      </div>
      <details className="rounded-lg border p-4">
        <summary className="cursor-pointer text-sm font-medium">
          {t("cause.not_a_problem")} (
          {items.filter((item) => item.branch === "not_a_problem").length})
        </summary>
        <div className="mt-3 space-y-3">
          {items
            .filter((item) => item.branch === "not_a_problem")
            .map((item) => (
              <EvidenceCard key={item.run_id} item={item} />
            ))}
        </div>
      </details>
    </section>
  );
}
function EvidenceCard({ item }: { item: ImprovementEvidenceItem }) {
  const t = useTranslations("improvement");
  return (
    <article className="space-y-3 rounded-xl border p-4 text-sm">
      <p className="text-muted-foreground text-xs">
        {t(item.kind === "train_eval" ? "trainExample" : "chatExample")}
      </p>
      <p className="font-medium break-words whitespace-pre-wrap">
        {item.question || t("unavailableAnswer")}
      </p>
      <p className="break-words whitespace-pre-wrap">{item.answer || t("unavailableAnswer")}</p>
      {item.comments.map((comment, index) => (
        <blockquote
          key={index}
          className="text-muted-foreground border-l-2 pl-3 break-words whitespace-pre-wrap"
        >
          {comment}
        </blockquote>
      ))}
      <details>
        <summary className="cursor-pointer">{t("whyCause")}</summary>
        <p className="text-muted-foreground mt-2 break-words">
          {item.reason ||
            t(
              item.branch === "unknown"
                ? "causeUnknown"
                : item.kind === "train_eval"
                  ? "causeTraining"
                  : "causeRecorded",
            )}
        </p>
      </details>
      {item.conversation_id && (
        <Link className="underline underline-offset-4" href={`/chat/${item.conversation_id}`}>
          {t("openConversation")}
        </Link>
      )}
    </article>
  );
}

export function TestQuestions({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const [skip, setSkip] = useState(0);
  const questions = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    skip,
    limit: 20,
  });
  if (questions.error) return <p role="alert">{getErrorMessage(questions.error, tErrors)}</p>;
  if (questions.isLoading) return <p role="status">{t("loading")}</p>;
  return (
    <section className="space-y-4">
      <h2 className="font-medium">
        {t("questionCount", { count: questions.total, version: session.dataset_version })}
      </h2>
      <p className="text-muted-foreground text-sm">{t("pinnedQuestions")}</p>
      {questions.total === 0 && <p>{t("noQuestions")}</p>}
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
    <section className="space-y-4">
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
      <p className="text-muted-foreground text-sm">
        {t("baselineUndecided", { count: arm.summary.incomplete + arm.summary.ungraded })}
      </p>
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
                  {grade.reason}
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
      >
        {t("openCheck")}
      </Link>
    </div>
  );
}
