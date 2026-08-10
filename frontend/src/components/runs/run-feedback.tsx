"use client";

import { useTranslations } from "next-intl";
import { MessageSquareText, ThumbsDown } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useRunTranscript } from "@/hooks";
import type { RunTranscriptMessage } from "@/types/runs";

function wasRatedDown(message: RunTranscriptMessage): boolean {
  // Either the reader's own thumb, or anybody's - the same "anybody" the run
  // list filters on, so a run marked 👎 in history has something to show here.
  return message.user_rating === -1 || (message.rating_count?.dislikes ?? 0) > 0;
}

/**
 * The answers in this run that somebody rated down, and what they said was wrong.
 *
 * This is the half that makes the dashboard's quality number actionable:
 * the card says quality fell, and this is where the conversations that did it are
 * read. It reads the run's transcript from `GET /runs/{run_id}/transcript`, keeps
 * the answers rated down, and shows the comment left with each.
 *
 * A failed request is an `ErrorState`, never an empty one: on this page an empty
 * state and a 502 would be the same pixels, and "nobody complained" is the
 * reassuring reading a failed fetch must not be allowed to borrow. A run with
 * nothing rated down is its own quiet, deliberate answer.
 */
export function RunFeedback({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const { transcript, isLoading, error } = useRunTranscript(runId);

  if (isLoading) return <LoadingState variant="skeleton-table" columns={1} rows={2} />;
  if (error || transcript === undefined) {
    return (
      <ErrorState
        title={t("feedbackCouldNotBeRead")}
        description={t("theFeedbackHappenedEither")}
      />
    );
  }

  const ratedDown = transcript.items.filter(wasRatedDown);
  if (ratedDown.length === 0) {
    return (
      <EmptyState
        icon={ThumbsDown}
        title={t("noAnswersRatedDown")}
        description={t("noAnswerInThisRun")}
      />
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-1.5 text-sm font-medium">
        <MessageSquareText className="h-4 w-4" />
        {t("whatPeopleSaidWasWrong")}
      </h3>
      <ul className="space-y-3">
        {ratedDown.map((message) => (
          <li key={message.id} className="border-destructive/40 rounded-md border-l-2 pl-3">
            {message.rating_comment ? (
              <p className="text-sm">{message.rating_comment}</p>
            ) : (
              <p className="text-muted-foreground text-sm italic">{t("ratedDownNoComment")}</p>
            )}
            {message.content && (
              <p className="text-muted-foreground mt-1 line-clamp-3 text-xs">{message.content}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
