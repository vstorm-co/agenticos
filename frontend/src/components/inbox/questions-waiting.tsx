"use client";

import Link from "next/link";
import { ChevronRight, MessageCircleQuestionMark } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { useWaitingChatQuestions } from "@/hooks/use-waiting-chat-questions";
import { ROUTES } from "@/lib/constants";

export function QuestionsWaiting({
  questions,
}: {
  questions: ReturnType<typeof useWaitingChatQuestions>;
}) {
  const t = useTranslations("inbox.questions");
  const format = useFormatter();
  const rows = new Map(questions.items.map((item) => [item.run_id, item]));
  return (
    <section aria-labelledby="inbox-questions" className="border-b last:border-b-0">
      <h2
        id="inbox-questions"
        data-tour="inbox-questions"
        className="text-muted-foreground px-4 pt-4 pb-2 text-xs font-medium sm:px-5"
      >
        {t("title")}
      </h2>
      {questions.error && (
        <div className="flex flex-wrap items-center gap-2 px-4 pb-3 text-sm sm:px-5">
          <span>{t("failed")}</span>
          <Button variant="outline" size="sm" onClick={() => void questions.refetch()}>
            {t("retry")}
          </Button>
        </div>
      )}
      <ul className="pb-2">
        {Array.from(rows.values(), (question) => (
          <li key={question.run_id}>
            <Link
              href={`${ROUTES.CHAT}?${new URLSearchParams({
                id: question.conversation_id,
                question: `${question.conversation_id}:${question.run_id}`,
              })}`}
              aria-label={t("open", {
                conversation: question.conversation_title ?? t("untitled"),
                agent: question.agent_name,
              })}
              className="hover:bg-muted/40 focus-visible:bg-muted/40 flex min-h-16 items-center gap-3 px-4 py-2.5 outline-offset-[-2px] sm:px-5"
            >
              <span className="bg-muted/50 flex size-8 shrink-0 items-center justify-center rounded-lg">
                <MessageCircleQuestionMark className="text-muted-foreground size-4" aria-hidden />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm font-medium wrap-anywhere">
                  {question.conversation_title ?? t("untitled")}
                </span>
                <span className="text-muted-foreground text-xs wrap-anywhere">
                  {t("source", {
                    agent: question.agent_name,
                    expiry: format.dateTime(new Date(question.expires_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                  })}
                </span>
              </span>
              <ChevronRight className="text-muted-foreground/60 size-4 shrink-0" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
      {questions.hasNextPage && (
        <div className="px-4 pb-3 sm:px-5">
          <Button
            variant="outline"
            size="sm"
            disabled={questions.isFetching}
            onClick={() => void questions.fetchNextPage()}
          >
            {t("loadMore")}
          </Button>
        </div>
      )}
    </section>
  );
}
