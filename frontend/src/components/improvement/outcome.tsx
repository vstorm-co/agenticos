"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { KnowledgeGapDialog } from "@/components/knowledge-gaps/knowledge-gap-dialog";
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import { useDatasetCases } from "@/hooks/use-datasets";
import { useEvalComparison } from "@/hooks/use-eval-runs";
import { useKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementIteration } from "@/types/improvement";

function counts(round: ImprovementIteration | undefined) {
  const fixed = round?.verdict_detail?.fixed;
  const broken = round?.verdict_detail?.broken;
  return fixed == null || broken == null ? null : { fixed: Number(fixed), broken: Number(broken) };
}

/** The drafts a person may add to the agent's knowledge bases, open and not yet added. */
function useDrafts(agentId: string) {
  const { topics, error } = useKnowledgeGaps({ kind: "agent", id: agentId });
  return { drafts: topics.filter((topic) => topic.has_draft && topic.can_edit), error };
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
  const { drafts } = useDrafts(session.agent_id);
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
  agentId,
  accept = false,
}: {
  agentId: string;
  accept?: boolean;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { drafts, error } = useDrafts(agentId);
  const [later, setLater] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const shown = drafts.filter((topic) => !later.includes(topic.id));
  return (
    <section className="min-w-0 space-y-3" data-tour="improvement-knowledge">
      <h3 className="text-sm font-medium">
        {accept ? t("acceptKnowledge", { count: shown.length }) : t("cause.missing_knowledge")}
      </h3>
      {error && <p role="alert">{getErrorMessage(error, tErrors)}</p>}
      {!accept && shown.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("noKnowledgeDocuments")}</p>
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
              <Button size="sm" variant="ghost" onClick={() => setLater([...later, topic.id])}>
                {t("notNow")}
              </Button>
            )}
          </div>
        </article>
      ))}
      {open && <KnowledgeGapDialog topicId={open} onClose={() => setOpen(null)} />}
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

/** Said only where an environment following new versions waits for its automatic check. */
export function GuardNote({ agentId, version }: { agentId: string; version: number }) {
  const t = useTranslations("improvement");
  const { environments } = useAgentEnvironments(agentId);
  const guarded = environments.filter(
    (environment) => environment.tracks_latest && environment.guard_suite_ids.length > 0,
  );
  return guarded.map((environment) => (
    <p key={environment.id} className="text-sm">
      {t("guardedSwitch", { environment: environment.name, version })}
    </p>
  ));
}

/** The end of the wizard: where the version is, and that a later break will be reported. */
export function DoneScreen({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
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
      <p className="text-muted-foreground text-sm">{t("doneWatching")}</p>
      <KnowledgeDocuments agentId={session.agent_id} accept />
    </section>
  );
}
