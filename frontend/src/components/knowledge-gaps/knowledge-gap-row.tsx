"use client";

import { Bot, Database, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";

interface KnowledgeGapRowProps {
  topic: KnowledgeGapTopic;
  /** On an agent's list, where the topics come from several knowledge bases. */
  showKnowledgeBase: boolean;
  onOpen: () => void;
}

/** One topic: its first question, how often it was asked, when last, and by which agents. */
export function KnowledgeGapRow({ topic, showKnowledgeBase, onOpen }: KnowledgeGapRowProps) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="hover:bg-accent/40 flex w-full flex-col gap-1.5 px-4 py-3 text-left"
      >
        <span className="text-foreground text-sm font-medium">{topic.label}</span>
        <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span>{t("questionCount", { count: topic.question_count })}</span>
          <span>{t("lastAsked", { ago: timeAgo(topic.last_asked_at, tTime, locale) })}</span>
          {showKnowledgeBase && (
            <Badge variant="outline">
              <Database className="h-3 w-3" aria-hidden />
              {topic.knowledge_base_name}
            </Badge>
          )}
          {topic.has_draft && (
            <Badge variant="outline">
              <Sparkles className="h-3 w-3" aria-hidden />
              {t("hasDraft")}
            </Badge>
          )}
          {topic.agents.map((agent) => (
            <Badge key={agent.id} variant="secondary">
              <Bot className="h-3 w-3" aria-hidden />
              {agent.name}
            </Badge>
          ))}
        </span>
      </button>
    </li>
  );
}
