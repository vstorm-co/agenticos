"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovementEvidence } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { EvidenceDecision, Improvement, ImprovementEvidenceItem } from "@/types/improvement";

type Column = "agent" | "missing_knowledge" | "not_a_problem";

function columnOf(item: ImprovementEvidenceItem): Column {
  return item.branch === "unknown" ? "agent" : item.branch;
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
  const tErrors = useTranslations("errors");
  const sources = useImprovementEvidence(session.agent_id, {
    sessionId: session.id,
    live: session.status === "running" || session.status === "queued",
  });
  const [error, setError] = useState<string | null>(null);
  if (sources.error) return <p role="alert">{getErrorMessage(sources.error, tErrors)}</p>;
  if (sources.isLoading || !sources.evidence) return <p role="status">{t("loading")}</p>;
  const items = sources.evidence.items;
  const kept = items.filter((item) => item.decision !== "ignored");
  const ignored = items.filter((item) => item.decision === "ignored");
  const topics = {
    agent: byTopic(kept.filter((item) => columnOf(item) === "agent")),
    missing_knowledge: byTopic(kept.filter((item) => columnOf(item) === "missing_knowledge")),
    not_a_problem: byTopic(kept.filter((item) => columnOf(item) === "not_a_problem")),
  };
  const canSort = !["accepted", "published", "rejected"].includes(session.status);
  async function decide(group: ImprovementEvidenceItem[], decision: EvidenceDecision | null) {
    setError(null);
    try {
      for (const item of group.filter((entry) => entry.kind === "chat"))
        await sources.decide.mutateAsync({ runId: item.run_id, decision });
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  const card = (group: ImprovementEvidenceItem[], column: Column | "ignored") => (
    <TopicCard
      key={group[0]!.run_id}
      items={group}
      busy={sources.decide.isPending}
      onMove={
        canSort && (column === "agent" || column === "missing_knowledge")
          ? () => void decide(group, column === "agent" ? "missing_knowledge" : "agent")
          : undefined
      }
      onIgnore={canSort && column !== "ignored" ? () => void decide(group, "ignored") : undefined}
      onRestore={canSort && column === "ignored" ? () => void decide(group, null) : undefined}
    />
  );
  return (
    <section className="space-y-4" data-tour="improvement-evidence">
      <h2 className="font-medium">{t("steps.understand")}</h2>
      <p className="text-lg font-medium">
        {t("problemsFound", {
          total: topics.agent.length + topics.missing_knowledge.length,
          agent: topics.agent.length,
          knowledge: topics.missing_knowledge.length,
        })}
      </p>
      <p className="text-muted-foreground text-sm">
        {t("evidenceSample", { count: items.length, limit: sources.evidence.sample_limit })}
      </p>
      {session.timeline.some((event) => event.action === "improvement.classification_failed") && (
        <p role="status" className="rounded-lg border p-3 text-sm">
          {t("classificationFailed")}
        </p>
      )}
      {items.length === 0 && <p className="text-sm">{t("noLearningExamples")}</p>}
      {kept.some((item) => item.branch === "unknown") && (
        <p className="rounded-lg border p-3 text-sm">{t("unknownCauses")}</p>
      )}
      {canSort && kept.some((item) => item.kind === "chat") && (
        <p className="text-muted-foreground text-sm">{t("sortingBody")}</p>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(["agent", "missing_knowledge"] as const).map((column) => (
          <section key={column} className="min-w-0 space-y-3">
            <h3 className="text-sm font-medium">
              {t(`cause.${column}`)}{" "}
              <span className="text-muted-foreground">({topics[column].length})</span>
            </h3>
            {topics[column].length ? (
              topics[column].map((group) => card(group, column))
            ) : (
              <p className="text-muted-foreground text-sm">{t("noExamplesInGroup")}</p>
            )}
          </section>
        ))}
      </div>
      <details className="rounded-lg border p-4">
        <summary className="cursor-pointer text-sm font-medium">
          {t("cause.not_a_problem")} ({topics.not_a_problem.length})
        </summary>
        <div className="mt-3 space-y-3">
          {topics.not_a_problem.map((group) => card(group, "not_a_problem"))}
        </div>
      </details>
      {ignored.length > 0 && (
        <details className="rounded-lg border p-4">
          <summary className="cursor-pointer text-sm font-medium">
            {t("ignoredExamples", { count: ignored.length })}
          </summary>
          <div className="mt-3 space-y-3">
            {byTopic(ignored).map((group) => card(group, "ignored"))}
          </div>
        </details>
      )}
    </section>
  );
}

function TopicCard({
  items,
  busy,
  onMove,
  onIgnore,
  onRestore,
}: {
  items: ImprovementEvidenceItem[];
  busy: boolean;
  onMove?: () => void;
  onIgnore?: () => void;
  onRestore?: () => void;
}) {
  const t = useTranslations("improvement");
  const [item, ...others] = items as [ImprovementEvidenceItem, ...ImprovementEvidenceItem[]];
  const sortable = items.some((entry) => entry.kind === "chat");
  return (
    <article className="space-y-3 rounded-xl border p-4 text-sm">
      <p className="text-muted-foreground text-xs">
        {others.length
          ? t("topicExamples", { count: items.length })
          : t(item.kind === "train_eval" ? "trainExample" : "chatExample")}
        {item.decision === "agent" || item.decision === "missing_knowledge"
          ? ` · ${t("movedByYou")}`
          : null}
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
      {others.length > 0 && (
        <details>
          <summary className="cursor-pointer">
            {t("otherExamples", { count: others.length })}
          </summary>
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
        </details>
      )}
      {sortable && (onMove || onIgnore || onRestore) && (
        <div className="flex flex-wrap gap-2">
          {onMove && (
            <Button variant="outline" size="sm" disabled={busy} onClick={onMove}>
              {t("moveColumn")}
            </Button>
          )}
          {onIgnore && (
            <Button variant="ghost" size="sm" disabled={busy} onClick={onIgnore}>
              {t("ignoreExample")}
            </Button>
          )}
          {onRestore && (
            <Button variant="outline" size="sm" disabled={busy} onClick={onRestore}>
              {t("restoreExample")}
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
