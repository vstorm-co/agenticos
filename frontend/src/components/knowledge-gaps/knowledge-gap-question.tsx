"use client";

import Link from "next/link";
import { ThumbsDown } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapQuestion } from "@/types/knowledge-gaps";

/**
 * One time the question was asked: in the person's words where the conversation
 * is kept, then what the agent searched for and how close the best match came.
 */
export function KnowledgeGapQuestionItem({ question }: { question: KnowledgeGapQuestion }) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const similarity =
    question.top_similarity === null
      ? null
      : question.top_similarity.toLocaleString(locale, { maximumFractionDigits: 2 });

  return (
    <li className="border-border space-y-1.5 rounded-lg border px-3 py-2.5 text-sm">
      <p className="text-foreground">{question.question ?? t("noConversation")}</p>
      <p className="text-muted-foreground">{t("searchedFor", { query: question.query })}</p>
      <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
        <span>
          {similarity === null
            ? t("noResults")
            : t("closestMatch", { count: question.result_count, similarity })}
        </span>
        {question.agent && <span>{question.agent.name}</span>}
        <span>{timeAgo(question.asked_at, tTime, locale)}</span>
        <Link href={`${ROUTES.RUNS}?run=${question.run_id}`} className="underline">
          {t("openRun")}
        </Link>
      </p>
      {question.down_rating_comment && (
        <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
          <ThumbsDown className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          {t("ratedDown", { comment: question.down_rating_comment })}
        </p>
      )}
    </li>
  );
}
