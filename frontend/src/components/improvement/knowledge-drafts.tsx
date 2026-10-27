"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button, Checkbox } from "@/components/ui";
import { KnowledgeGapDialog } from "@/components/knowledge-gaps/knowledge-gap-dialog";
import { usd } from "@/components/evals/format";
import { useDatasetCases } from "@/hooks/use-datasets";
import { useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { useImprovement } from "@/hooks/use-improvements";
import { useKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { KnowledgeGapDraftStatus } from "@/components/knowledge-gaps/knowledge-gap-draft-status";
import { getErrorMessage } from "@/lib/api-error";
import type {
  Improvement,
  KnowledgeCheckEstimate,
  KnowledgeCheckTarget,
} from "@/types/improvement";
import { useSessionTopics } from "./outcome";
import { useReadOnly } from "./read-only";

/** A paid draft check is separate from accepting or publishing the agent. */
export function KnowledgeDrafts({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const readOnly = useReadOnly();
  const { topics, error: topicsError } = useSessionTopics(session);
  const [topicId, setTopicId] = useState("");
  const [mode, setMode] = useState<"context" | "retrieval">("context");
  const [selected, setSelected] = useState<string[]>([]);
  const [skip, setSkip] = useState(0);
  const questions = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    skip,
    limit: 20,
  });
  const [quoted, setQuoted] = useState<{
    key: string;
    target: KnowledgeCheckTarget;
    quote: KnowledgeCheckEstimate;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const round =
    session.iterations.find((item) => item.id === session.best_iteration_id) ??
    (session.stop_reason === "knowledge_only"
      ? session.iterations.find((item) => item.number === session.iteration)
      : undefined);
  const target: KnowledgeCheckTarget = {
    topic_id: topicId,
    mode,
    round: round?.number ?? 1,
    case_ids: selected,
  };
  const key = JSON.stringify(target);
  const current = quoted?.key === key ? quoted : null;
  const drafts = topics.filter((topic) => topic.has_draft && topic.can_edit && !topic.drafting);
  const undrafted = topics.filter(
    (topic) => !topic.has_draft || topic.drafting || topic.draft_failed || topic.draft_stale,
  );
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6">
      <h3 className="font-medium">{t("knowledgeTitle")}</h3>
      <p className="text-muted-foreground text-sm">{t("knowledgeSeparate")}</p>
      {session.timeline.some((event) => event.action === "improvement.drafting_failed") && (
        <p role="status" className="text-sm">
          {t("draftingFailed")}
        </p>
      )}
      <div role="group" aria-label={t("knowledgeMode")} className="flex flex-wrap gap-2">
        {(["context", "retrieval"] as const).map((value) => (
          <Button
            key={value}
            variant={value === mode ? "secondary" : "outline"}
            className="h-auto max-w-full text-center whitespace-normal"
            aria-pressed={value === mode}
            onClick={() => setMode(value)}
          >
            {t(value === "context" ? "contextMode" : "retrievalMode")}
          </Button>
        ))}
      </div>
      {(topicsError || questions.error) && (
        <p role="alert">{getErrorMessage(topicsError ?? questions.error, tErrors)}</p>
      )}
      {drafts.length > 0 && round && !readOnly && ["ready", "stopped"].includes(session.status) ? (
        <>
          <label className="block space-y-2 text-sm">
            <span>{t("chooseDraft")}</span>
            <select
              className="bg-background w-full rounded-lg border p-2"
              value={topicId}
              onChange={(event) => setTopicId(event.target.value)}
            >
              <option value="">{t("chooseDraft")}</option>
              {drafts.map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.label}
                </option>
              ))}
            </select>
          </label>
          {topicId && (
            <DraftFacts
              key={topicId}
              topicId={topicId}
              supported={current?.quote.supported}
              mode={mode}
            />
          )}
          <fieldset className="space-y-3">
            <legend className="mb-3 text-sm font-medium">{t("knowledgeQuestions")}</legend>
            <p className="text-muted-foreground text-sm">{t("knowledgeQuestionsBody")}</p>
            {questions.cases.map((item) => (
              <label key={item.case_id} className="flex items-start gap-2 text-sm">
                <Checkbox
                  className="mt-0.5"
                  checked={selected.includes(item.case_id)}
                  disabled={
                    item.masked ||
                    item.improvement_partition === "train" ||
                    Boolean(item.anonymised_at)
                  }
                  onCheckedChange={(checked) =>
                    setSelected((held) =>
                      checked === true
                        ? [...held, item.case_id]
                        : held.filter((id) => id !== item.case_id),
                    )
                  }
                />
                <span className="break-words">{item.input}</span>
              </label>
            ))}
            <div className="flex gap-3">
              <Button
                variant="ghost"
                disabled={skip === 0}
                onClick={() => setSkip(Math.max(0, skip - 20))}
              >
                {t("previousQuestions")}
              </Button>
              <Button
                variant="ghost"
                disabled={skip + 20 >= questions.total}
                onClick={() => setSkip(skip + 20)}
              >
                {t("nextQuestions")}
              </Button>
            </div>
          </fieldset>
          <Button
            className="h-auto max-w-full text-center whitespace-normal"
            variant="outline"
            disabled={!topicId || selected.length === 0 || actions.estimateKnowledge.isPending}
            onClick={() =>
              void act(async () => {
                const quote = await actions.estimateKnowledge.mutateAsync(target);
                setQuoted({ key, target, quote });
              })
            }
          >
            {t("estimateKnowledge")}
          </Button>
          {current && (
            <div className="space-y-3 text-sm">
              <p>
                {current.quote.can_measure
                  ? t("knowledgeQuote", {
                      cost: usd(current.quote.total_usd, locale),
                      count: current.quote.cases,
                      excluded: current.quote.excluded,
                    })
                  : t(
                      current.quote.reason === "untracked_draft_sources"
                        ? "knowledgeUntracked"
                        : current.quote.reason === "embedding_unavailable"
                          ? "knowledgeEmbeddingUnavailable"
                          : current.quote.reason === "embedding_price_unavailable"
                            ? "knowledgeEmbeddingPriceUnavailable"
                            : current.quote.reason === "knowledge_search_disabled"
                              ? "knowledgeSearchDisabled"
                              : "knowledgeUnmeasurable",
                    )}
              </p>
              <Button
                className="h-auto max-w-full text-center whitespace-normal"
                disabled={
                  !current.quote.affordable ||
                  !current.quote.can_measure ||
                  actions.checkKnowledge.isPending
                }
                onClick={() =>
                  void act(async () => {
                    await actions.checkKnowledge.mutateAsync({
                      ...current.target,
                      confirmed: true,
                      draft_hash: current.quote.draft_hash,
                      estimate_usd: current.quote.total_usd,
                    });
                    setQuoted(null);
                  })
                }
              >
                {t("confirmKnowledge")}
              </Button>
            </div>
          )}
        </>
      ) : (
        <p className="text-muted-foreground text-sm">{t("noKnowledgeDrafts")}</p>
      )}
      {undrafted.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("draftToTest")}</p>
          <ul className="space-y-2">
            {undrafted.map((topic) => (
              <li key={topic.id} className="space-y-1 rounded-lg border p-3 text-sm">
                <p className="break-words">{topic.label}</p>
                <KnowledgeGapDraftStatus topic={topic} editable={!readOnly && topic.can_edit} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {(session.knowledge_eval_run_ids ?? []).map((id) => (
        <KnowledgeResult key={id} runId={id} agentId={session.agent_id} refresh={actions.refetch} />
      ))}
    </section>
  );
}

function DraftFacts({
  topicId,
  supported,
  mode,
}: {
  topicId: string;
  supported?: boolean;
  mode: "context" | "retrieval";
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { topic, error } = useKnowledgeGap(topicId);
  const [open, setOpen] = useState(false);
  const readOnly = useReadOnly();
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  return (
    <div className="space-y-3 text-sm">
      <p>{t(mode === "retrieval" ? "retrievalAssumption" : "contextAssumption")}</p>
      {topic?.draft && (
        <>
          {!(supported ?? topic.draft.sources.some((source) => source.kind === "document")) && (
            <p className="text-warning">{t("unsupportedDraft")}</p>
          )}
          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer font-medium">{topic.draft.title}</summary>
            <p className="mt-3 break-words whitespace-pre-wrap">{topic.draft.content}</p>
          </details>
        </>
      )}
      {!readOnly && (
        <Button
          className="h-auto max-w-full text-center whitespace-normal"
          variant="outline"
          onClick={() => setOpen(true)}
        >
          {t("reviewKnowledgeDraft")}
        </Button>
      )}
      {open && <KnowledgeGapDialog topicId={topicId} onClose={() => setOpen(false)} wizard />}
    </div>
  );
}

function KnowledgeResult({
  runId,
  agentId,
  refresh,
}: {
  runId: string;
  agentId: string;
  refresh: () => Promise<unknown>;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { run, error } = useEvalRun(runId);
  const active = run?.status === "queued" || run?.status === "running";
  const { comparison, error: comparisonError } = useEvalComparison(runId, { live: active });
  const record = run?.proposal_check?.knowledge;
  const status = run?.status;
  useEffect(() => {
    if (status && !["queued", "running"].includes(status)) void refresh();
  }, [status, refresh]);
  return (
    <article className="space-y-3 border-t pt-4 text-sm">
      <p className="font-medium">{t("knowledgeTitle")}</p>
      <p>{t(record?.mode === "retrieval" ? "retrievalAssumption" : "contextAssumption")}</p>
      {record && !record.supported && <p className="text-warning">{t("unsupportedDraft")}</p>}
      {error || comparisonError ? (
        <p role="alert">{getErrorMessage(error ?? comparisonError, tErrors)}</p>
      ) : record?.invalidated ? (
        <p>{t("knowledgeInvalidated")}</p>
      ) : active || !run ? (
        <p role="status">{t("working")}</p>
      ) : run.status !== "completed" ? (
        <p role="alert">{t("attributionUnavailable")}</p>
      ) : comparison?.verdict === "invalid" &&
        comparison.invalid_reason_code === "knowledge_not_retrieved" ? (
        <p>{t("knowledgeNotRetrieved")}</p>
      ) : (
        comparison && (
          <p>
            {t(
              `verdict.${comparison.verdict === "better" ? "better" : comparison.verdict === "worse" || comparison.regressions_confirmed > 0 ? "regression" : comparison.verdict === "invalid" ? "inconclusive" : "no_change"}`,
              { fixed: comparison.fixed_confirmed, broken: comparison.regressions_confirmed },
            )}
          </p>
        )
      )}
      <Link className="underline" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </article>
  );
}
