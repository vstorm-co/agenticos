"use client";

import { Database, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Badge } from "@/components/ui";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { KnowledgeGapActions } from "./knowledge-gap-actions";

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
    <li className="hover:bg-accent/40 flex items-start gap-2 pr-3">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-col gap-1.5 py-3 pl-4 text-left sm:pl-5"
      >
        <span className="text-foreground text-sm font-medium break-words">{topic.label}</span>
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
            <span key={agent.id} className="inline-flex items-center gap-1">
              <AgentAvatar
                agentId={agent.id}
                slug={agent.slug}
                hasAvatar={agent.has_avatar}
                colorSlot={agent.avatar_color}
                size="sm"
              />
              {agent.name}
            </span>
          ))}
        </span>
      </button>
      <div className="pt-2">
        <KnowledgeGapActions topic={topic} />
      </div>
    </li>
  );
}
