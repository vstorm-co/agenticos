"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { KnowledgeGapDialog } from "@/components/knowledge-gaps/knowledge-gap-dialog";
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { useDatasetCases } from "@/hooks/use-datasets";
import { useEvalComparison } from "@/hooks/use-eval-runs";
import { useImprovement, useImprovementEvidence } from "@/hooks/use-improvements";
import { useKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { StepError } from "./step-error";

function counts(round: ImprovementIteration | undefined) {
  const fixed = round?.verdict_detail?.fixed;
  const broken = round?.verdict_detail?.broken;
  return fixed == null || broken == null ? null : { fixed: Number(fixed), broken: Number(broken) };
}

/**
 * The drafts this session's own examples led to that a person may add: open, not yet
 * added, and on a topic one of the session's conversations missed.
 */
function useDrafts(session: Improvement) {
  const gaps = useKnowledgeGaps({ kind: "agent", id: session.agent_id });
  const sources = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const { topics } = gaps;
  const { evidence } = sources;
  const ours = new Set(evidence?.items.map((item) => item.topic_id).filter(Boolean));
  return {
    drafts: topics.filter((topic) => topic.has_draft && topic.can_edit && ours.has(topic.id)),
    error: gaps.error ?? sources.error,
    retry: () => Promise.all([gaps.refetch(), sources.refetch()]),
  };
}

/** One sentence for the agent and one for the knowledge base, before the details. */
export function ResultSummary({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration | undefined;
}) {
  const t = useTranslations("improvement");
  const { drafts } = useDrafts(session);
  const measured = counts(round);
  return (
    <div className="space-y-1 rounded-xl border p-4 text-sm">
      <p>{measured ? t("resultAgent", measured) : t("resultAgentUnknown")}</p>
      <p>{t("resultKnowledge", { count: drafts.length })}</p>
    </div>
  );
}

/** The column of knowledge drafts beside the agent's changes, or the list to add on Accept. */
export function KnowledgeDocuments({
  session,
  accept = false,
}: {
  session: Improvement;
  accept?: boolean;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { drafts, error, retry } = useDrafts(session);
  const actions = useImprovement(session.agent_id, session.id);
  const [open, setOpen] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const later = session.deferred_topic_ids ?? [];
  const shown = accept ? drafts.filter((topic) => !later.includes(topic.id)) : drafts;
  return (
    <section className="min-w-0 space-y-3" data-tour="improvement-knowledge">
      <h3 className="text-sm font-medium">
        {accept ? t("acceptKnowledge", { count: shown.length }) : t("cause.missing_knowledge")}
      </h3>
      {error && <StepError error={error} retry={retry} />}
      {session.timeline.some(
        (event) =>
          event.action === "improvement.drafting_finished" && event.reason === "too_few_askers",
      ) ? (
        <p className="text-muted-foreground text-sm">
          {t("draftsTooFewAskers")}{" "}
          <Link
            className="underline underline-offset-4"
            href={`/agents/${session.agent_id}?tab=gaps`}
          >
            {t("openKnowledgeGaps")}
          </Link>
        </p>
      ) : (
        !accept &&
        shown.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("noKnowledgeDocuments")}</p>
        )
      )}
      {shown.map((topic) => (
        <article key={topic.id} className="space-y-2 rounded-xl border p-4 text-sm">
          <p className="font-medium break-words">{topic.label}</p>
          <p className="text-muted-foreground text-xs">{topic.knowledge_base_name}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setOpen(topic.id)}>
              {t(accept ? "reviewAndAdd" : "reviewKnowledgeDraft")}
            </Button>
            {accept && (
              <Button
                size="sm"
                variant="ghost"
                disabled={actions.deferTopic.isPending}
                onClick={() =>
                  void actions.deferTopic.mutateAsync({ topicId: topic.id, later: true }).then(
                    () => setFailure(null),
                    (reason: unknown) => setFailure(getErrorMessage(reason, tErrors)),
                  )
                }
              >
                {t("notNow")}
              </Button>
            )}
          </div>
        </article>
      ))}
      {failure && (
        <p role="alert" className="text-destructive text-sm">
          {failure}
        </p>
      )}
      {open && <KnowledgeGapDialog topicId={open} onClose={() => setOpen(null)} wizard />}
    </section>
  );
}

/** "Version N will fix X, break Y, cost Z% per answer", from the measured round. */
export function AcceptSummary({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration | undefined;
}) {
  const t = useTranslations("improvement");
  const measured = counts(round);
  const runId = round?.eval_run_ids.at(-1);
  const questions = useDatasetCases(session.dataset_id, {
    version: session.dataset_version,
    limit: 1,
  });
  if (!measured || !runId) return <p className="text-sm">{t("resultAgentUnknown")}</p>;
  return (
    <AgentSentence
      runId={runId}
      version={session.next_version ?? null}
      total={questions.total}
      {...measured}
    />
  );
}

function AgentSentence({
  runId,
  version,
  total,
  fixed,
  broken,
}: {
  runId: string;
  version: number | null;
  total: number;
  fixed: number;
  broken: number;
}) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const { comparison } = useEvalComparison(runId);
  const before = comparison?.baseline_summary;
  const after = comparison?.candidate_summary;
  const perAnswer = (cost: string, cases: number) => Number(cost) / Math.max(1, cases);
  const change =
    before && after && perAnswer(before.cost_usd, before.cases) > 0
      ? perAnswer(after.cost_usd, after.cases) / perAnswer(before.cost_usd, before.cases) - 1
      : null;
  return (
    <p className="text-sm">
      {t("acceptAgent", {
        version: version ?? 0,
        fixed,
        broken,
        costKnown: change === null ? "no" : "yes",
        cost:
          change === null
            ? ""
            : new Intl.NumberFormat(locale, {
                style: "percent",
                signDisplay: "always",
                maximumFractionDigits: 0,
              }).format(change),
        total,
        heldOut: after?.cases ?? 0,
      })}
    </p>
  );
}

/**
 * Where people use the agent, one sentence each: a place that follows new versions
 * switches at once or after its automatic check passes, and any other stays put.
 */
export function GuardNote({ agentId, version }: { agentId: string; version: number }) {
  const t = useTranslations("improvement");
  const { environments } = useAgentEnvironments(agentId);
  return environments.map((environment) => (
    <p key={environment.id} className="text-sm">
      {!environment.tracks_latest
        ? t("environmentStays", { environment: environment.name, version: environment.version })
        : environment.guard_suite_ids.length > 0
          ? t("guardedSwitch", { environment: environment.name, version })
          : t("environmentSwitches", { environment: environment.name, version })}
    </p>
  ));
}

/** The end of the wizard: where the version is, and that a later break will be reported. */
export function DoneScreen({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const { suites } = useAgentEvalSuites(session.agent_id);
  return (
    <section
      className="space-y-3 rounded-xl border p-6"
      data-tour="improvement-done"
      aria-label={t("doneTitle")}
    >
      <h2 className="text-lg font-medium">{t("doneTitle")}</h2>
      {session.status === "published" && session.published_version != null ? (
        <>
          <p role="status" className="text-sm">
            {t("donePublished", { version: session.published_version })}
          </p>
          <GuardNote agentId={session.agent_id} version={session.published_version} />
          <Link
            className="text-sm underline"
            href={`/agents/${session.agent_id}?tab=history&from=${session.published_version}&to=${session.published_version}`}
          >
            {t("openVersion", { version: session.published_version })}
          </Link>
        </>
      ) : (
        <p role="status" className="text-sm">
          {t("doneDraft")}
        </p>
      )}
      {suites.length > 0 ? (
        <p className="text-muted-foreground text-sm">{t("doneWatching")}</p>
      ) : (
        <p className="text-muted-foreground text-sm">
          {t("doneUnwatched")}{" "}
          <Link
            className="underline underline-offset-4"
            href={`/agents/${session.agent_id}?tab=evals`}
          >
            {t("setUpAutomaticCheck")}
          </Link>
        </p>
      )}
      <KnowledgeDocuments session={session} accept />
    </section>
  );
}
