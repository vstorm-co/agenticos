"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ChangePreview } from "@/components/authoring/result-dialog";
import { LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { useImprovementChanges, useImprovementEvidence } from "@/hooks/use-improvements";
import { useKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import type { Improvement } from "@/types/improvement";
import { StepError } from "./step-error";

/** The timeline entries that end a session, as the API records them. */
const ENDINGS = new Set([
  "improvement.published",
  "improvement.accepted",
  "improvement.discarded",
  "improvement.rejected",
  "improvement.cancelled",
  "improvement.stale",
]);

function Changes({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.decision");
  const { changes, isLoading, error, refetch } = useImprovementChanges(
    session.agent_id,
    session.id,
  );
  const { evidence } = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const sources = Object.fromEntries((evidence?.items ?? []).map((item) => [item.run_id, item]));
  if (isLoading) return <LoadingState variant="skeleton-list" rows={2} />;
  if (error) return <StepError error={error} retry={refetch} />;
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">{t("changes", { count: changes.length })}</h3>
      {changes.length === 0 && <p className="text-muted-foreground text-sm">{t("noChanges")}</p>}
      {changes.map((hunk) => (
        <article key={hunk.id} className="space-y-2">
          <Badge variant={hunk.status === "accepted" ? "success" : "secondary"}>
            {t(`changeState.${hunk.status}`)}
          </Badge>
          <ChangePreview hunk={hunk} sources={sources} />
        </article>
      ))}
    </section>
  );
}

function Knowledge({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.decision");
  const { topics } = useKnowledgeGaps({ kind: "agent", id: session.agent_id });
  const { evidence } = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const ours = new Set(evidence?.items.map((item) => item.topic_id).filter(Boolean));
  const later = session.deferred_topic_ids ?? [];
  const documents = topics.filter((topic) => ours.has(topic.id));
  if (documents.length === 0) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">{t("knowledge")}</h3>
      <ul className="space-y-1 text-sm">
        {documents.map((topic) => (
          <li key={topic.id} className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 break-words">{topic.label}</span>
            <Badge variant="outline">
              {t(
                later.includes(topic.id)
                  ? "knowledgeState.later"
                  : topic.status === "covered"
                    ? "knowledgeState.added"
                    : "knowledgeState.notAdded",
              )}
            </Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AutomaticCheck({ session, at }: { session: Improvement; at: string }) {
  const t = useTranslations("improvement.decision");
  const { suites } = useAgentEvalSuites(session.agent_id);
  const made = suites.some(
    (suite) =>
      suite.dataset_id === session.dataset_id &&
      suite.created_at >= session.created_at &&
      suite.created_at <= at,
  );
  return (
    <p className="text-muted-foreground text-sm">
      {t(made ? "checkMade" : suites.length > 0 ? "checkKept" : "checkNone")}
    </p>
  );
}

/**
 * How a finished session ended, for its last step: what was decided, by whom and
 * when, the changes it measured as they were decided, what became of the
 * knowledge documents it drafted, and whether an automatic check guards the agent.
 */
export function SessionDecision({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.decision");
  const locale = useLocale();
  const ending = [...session.timeline].reverse().find((event) => ENDINGS.has(event.action));
  const at = ending?.at ?? session.finished_at ?? session.created_at;
  const when = new Date(at).toLocaleString(locale);
  const version = session.published_version;
  return (
    <section
      className="space-y-4 rounded-xl border p-6"
      data-tour="improvement-decision"
      aria-label={t("title")}
    >
      <h2 className="font-medium">{t("title")}</h2>
      <div className="space-y-1">
        <p role="status" className="text-sm font-semibold">
          {session.status === "published" && version != null
            ? t("publishedVersion", { version })
            : t(`outcome.${session.status}`)}
        </p>
        <p className="text-muted-foreground text-sm">
          {ending?.actor_name
            ? t("by", { name: ending.actor_name, at: when })
            : t("at", { at: when })}
        </p>
        {session.status === "published" && version != null && (
          <Link
            className="text-sm underline underline-offset-4"
            href={`/agents/${session.agent_id}?tab=history&from=${version}&to=${version}`}
          >
            {t("openVersion", { version })}
          </Link>
        )}
      </div>
      <Changes session={session} />
      <Knowledge session={session} />
      <AutomaticCheck session={session} at={at} />
    </section>
  );
}
