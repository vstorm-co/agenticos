"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { KnowledgeGapDraftStatus } from "@/components/knowledge-gaps/knowledge-gap-draft-status";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { useReadOnly } from "./read-only";

interface SessionTopicProps {
  topic: KnowledgeGapTopic;
  /** On Accept, where a drafted topic is added or set aside for later. */
  accept: boolean;
  onReview: () => void;
  /** Sets the topic aside; offered on Accept only. */
  onLater?: () => void;
  laterPending?: boolean;
}

/**
 * One topic a session found missing from the knowledge base: the questions behind
 * it and where its draft stands. Nothing is drafted until somebody asks here, and
 * a drafted topic is reviewed and added from its dialog.
 */
export function SessionTopic({
  topic,
  accept,
  onReview,
  onLater,
  laterPending,
}: SessionTopicProps) {
  const t = useTranslations("improvement");
  const readOnly = useReadOnly();
  const drafted = topic.has_draft && !topic.drafting;
  const reviewable = drafted && topic.can_edit;
  const others = topic.examples.filter((example) => example !== topic.label);
  return (
    <article className="space-y-2 rounded-xl border p-4 text-sm">
      <p className="font-medium break-words">{topic.label}</p>
      {others.length > 0 && (
        <ul
          aria-label={t("topicQuestions")}
          className="text-muted-foreground list-disc space-y-1 pl-5 text-xs break-words"
        >
          {others.map((example) => (
            <li key={example}>{example}</li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground text-xs">{topic.knowledge_base_name}</p>
      {drafted && topic.draft_askers === 1 && (
        <p className="text-warning text-xs">{t("draftFromOnePerson")}</p>
      )}
      <KnowledgeGapDraftStatus topic={topic} editable={!readOnly && topic.can_edit} />
      {!readOnly && (reviewable || onLater) && (
        <div className="flex flex-wrap gap-2">
          {reviewable && (
            <Button size="sm" variant="outline" onClick={onReview}>
              {t(accept ? "reviewAndAdd" : "reviewKnowledgeDraft")}
            </Button>
          )}
          {onLater && (
            <Button size="sm" variant="ghost" disabled={laterPending} onClick={onLater}>
              {t("notNow")}
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
