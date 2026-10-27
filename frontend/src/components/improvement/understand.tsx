"use client";

import Link from "next/link";
import { BookCheck, MessageSquareQuote } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useImprovementEvidence } from "@/hooks/use-improvements";
import { ROUTES } from "@/lib/constants";
import type { Improvement, ImprovementEvidenceItem, KnowledgeAdded } from "@/types/improvement";
import { StepError } from "./step-error";
import { Details, Proportion } from "./widgets";

type Column = "agent" | "missing_knowledge" | "knowledge_added" | "not_a_problem";

const COLUMN_FILL = {
  agent: "var(--series-3)",
  missing_knowledge: "var(--series-2)",
  knowledge_added: "var(--series-1)",
};

/** A miss whose topic a document covers since has nothing left to draft. */
function columnOf(item: ImprovementEvidenceItem): Column {
  if (item.branch === "unknown") return "agent";
  if (item.branch === "missing_knowledge" && item.knowledge_added) return "knowledge_added";
  return item.branch;
}

/** Examples whose misses joined one knowledge gap topic are one problem. */
function byTopic(items: ImprovementEvidenceItem[]): ImprovementEvidenceItem[][] {
  const groups = new Map<string, ImprovementEvidenceItem[]>();
  for (const item of items) {
    const key = item.topic_id ?? item.run_id;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.values()];
}

export function Understand({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const sources = useImprovementEvidence(session.agent_id, {
    sessionId: session.id,
    live: session.status === "running" || session.status === "queued",
  });
  if (sources.error) return <StepError error={sources.error} retry={sources.refetch} />;
  if (sources.isLoading || !sources.evidence) return <p role="status">{t("loading")}</p>;
  const items = sources.evidence.items;
  const topics = {
    agent: byTopic(items.filter((item) => columnOf(item) === "agent")),
    missing_knowledge: byTopic(items.filter((item) => columnOf(item) === "missing_knowledge")),
    knowledge_added: byTopic(items.filter((item) => columnOf(item) === "knowledge_added")),
    not_a_problem: byTopic(items.filter((item) => columnOf(item) === "not_a_problem")),
  };
  const card = (group: ImprovementEvidenceItem[]) => (
    <TopicCard key={group[0]!.run_id} items={group} />
  );
  const found = t("problemsFound", {
    total: topics.agent.length + topics.missing_knowledge.length + topics.knowledge_added.length,
    agent: topics.agent.length,
    knowledge: topics.missing_knowledge.length,
    added: topics.knowledge_added.length,
  });
  return (
    <section className="space-y-5" data-tour="improvement-evidence">
      <h2 className="font-medium">{t("steps.understand")}</h2>
      <figure className="space-y-3 rounded-xl border p-4">
        <figcaption className="text-lg font-medium">{found}</figcaption>
        <Proportion
          label={found}
          parts={[
            { label: t("cause.agent"), value: topics.agent.length, fill: COLUMN_FILL.agent },
            {
              label: t("cause.missing_knowledge"),
              value: topics.missing_knowledge.length,
              fill: COLUMN_FILL.missing_knowledge,
            },
            {
              label: t("cause.knowledge_added"),
              value: topics.knowledge_added.length,
              fill: COLUMN_FILL.knowledge_added,
            },
            {
              label: t("cause.not_a_problem"),
              value: topics.not_a_problem.length,
              fill: "bg-muted-foreground/40",
            },
          ]}
        />
      </figure>
      {session.timeline.some((event) => event.action === "improvement.classification_failed") && (
        <p role="status" className="rounded-lg border p-3 text-sm">
          {t("classificationFailed")}
        </p>
      )}
      {items.length === 0 && <p className="text-sm">{t("noLearningExamples")}</p>}
      {items.some((item) => item.branch === "unknown") && (
        <p className="text-muted-foreground text-sm">{t("unknownCauses")}</p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(["agent", "missing_knowledge"] as const).map((column) => (
          <section
            key={column}
            className="bg-muted/30 min-w-0 space-y-3 rounded-xl border p-3"
            aria-label={t(`cause.${column}`)}
          >
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <span
                aria-hidden
                className="size-2.5 shrink-0 rounded-[3px]"
                style={{ background: COLUMN_FILL[column] }}
              />
              <span className="flex-1">{t(`cause.${column}`)}</span>
              <span
                aria-hidden
                className="bg-background rounded-full border px-2 text-xs tabular-nums"
              >
                {topics[column].length}
              </span>
              <span className="sr-only">({topics[column].length})</span>
            </h3>
            {topics[column].length ? (
              topics[column].map(card)
            ) : (
              <p className="text-muted-foreground text-sm">{t("noExamplesInGroup")}</p>
            )}
          </section>
        ))}
      </div>
      {topics.knowledge_added.length > 0 && (
        <section
          className="bg-muted/30 min-w-0 space-y-3 rounded-xl border p-3"
          aria-label={t("cause.knowledge_added")}
        >
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <span
              aria-hidden
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: COLUMN_FILL.knowledge_added }}
            />
            <span className="flex-1">{t("cause.knowledge_added")}</span>
            <span
              aria-hidden
              className="bg-background rounded-full border px-2 text-xs tabular-nums"
            >
              {topics.knowledge_added.length}
            </span>
            <span className="sr-only">({topics.knowledge_added.length})</span>
          </h3>
          <p className="text-muted-foreground text-sm">{t("knowledgeAddedHint")}</p>
          {topics.knowledge_added.map(card)}
        </section>
      )}
      <Details summary={`${t("cause.not_a_problem")} (${topics.not_a_problem.length})`}>
        {topics.not_a_problem.map(card)}
      </Details>
      <p className="text-muted-foreground text-xs">
        {t("evidenceSample", { count: items.length, limit: sources.evidence.sample_limit })}
      </p>
    </section>
  );
}

function TopicCard({ items }: { items: ImprovementEvidenceItem[] }) {
  const t = useTranslations("improvement");
  const [item, ...others] = items as [ImprovementEvidenceItem, ...ImprovementEvidenceItem[]];
  return (
    <article className="bg-background rounded-xl border text-sm">
      <details>
        <summary className="hover:bg-muted/50 cursor-pointer space-y-1.5 rounded-xl p-3">
          <span className="line-clamp-2 font-medium break-words">
            {item.question || t("unavailableAnswer")}
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground text-xs">
              {others.length
                ? t("topicExamples", { count: items.length })
                : t(item.kind === "train_eval" ? "trainExample" : "chatExample")}
            </span>
            {item.knowledge_added && <KnowledgeAddedNote added={item.knowledge_added} />}
            {item.comments.length > 0 && (
              <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                <MessageSquareQuote className="size-3.5" aria-hidden />
                {t("widgets.comments", { count: item.comments.length })}
              </span>
            )}
          </span>
        </summary>
        <div className="space-y-3 border-t p-3">
          <p className="break-words whitespace-pre-wrap">{item.answer || t("unavailableAnswer")}</p>
          {item.comments.map((comment, index) => (
            <blockquote
              key={index}
              className="text-muted-foreground border-l-2 pl-3 break-words whitespace-pre-wrap"
            >
              {comment}
            </blockquote>
          ))}
          <div>
            <h4 className="text-xs font-medium">{t("whyCause")}</h4>
            <p className="text-muted-foreground mt-1 break-words">
              {item.reason ||
                t(
                  item.branch === "unknown"
                    ? "causeUnknown"
                    : item.kind === "train_eval"
                      ? "causeTraining"
                      : "causeRecorded",
                )}
            </p>
          </div>
          {item.conversation_id && (
            <Link className="underline underline-offset-4" href={`/chat/${item.conversation_id}`}>
              {t("openConversation")}
            </Link>
          )}
          {others.length > 0 && (
            <div>
              <h4 className="text-xs font-medium">
                {t("otherExamples", { count: others.length })}
              </h4>
              <ul className="mt-2 space-y-2">
                {others.map((other) => (
                  <li key={other.run_id} className="break-words">
                    {other.question || t("unavailableAnswer")}{" "}
                    {other.conversation_id && (
                      <Link
                        className="underline underline-offset-4"
                        href={`/chat/${other.conversation_id}`}
                      >
                        {t("openConversation")}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </article>
  );
}

function KnowledgeAddedNote({ added }: { added: KnowledgeAdded }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  return (
    <span className="text-muted-foreground inline-flex min-w-0 items-center gap-1 text-xs">
      <BookCheck className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">
        {t.rich("knowledgeAddedOn", {
          name: added.filename,
          dated: added.added_at ? "yes" : "no",
          date: added.added_at
            ? new Date(added.added_at).toLocaleDateString(locale, {
                month: "short",
                day: "numeric",
              })
            : "",
          link: (chunks) => (
            <Link
              href={`${ROUTES.RAG_DETAIL(added.knowledge_base_id)}?tab=documents`}
              className="underline underline-offset-4"
            >
              {chunks}
            </Link>
          ),
        })}
      </span>
    </span>
  );
}
