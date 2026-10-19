"use client";

import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { KnowledgeGapActions } from "./knowledge-gap-actions";
import { KnowledgeGapDraftPanel } from "./knowledge-gap-draft";
import { KnowledgeGapQuestionItem } from "./knowledge-gap-question";

interface KnowledgeGapDialogProps {
  topicId: string;
  onClose: () => void;
}

/** A topic's questions, newest first, with what each search found and what to do about it. */
export function KnowledgeGapDialog({ topicId, onClose }: KnowledgeGapDialogProps) {
  const t = useTranslations("knowledgeGaps");
  const { topic, isLoading, error, refetch } = useKnowledgeGap(topicId);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_COLUMN)}>
        <DialogHeader className="pr-8">
          <div className="flex items-start justify-between gap-2">
            <DialogTitle className="break-words">{topic?.label ?? t("topic")}</DialogTitle>
            {topic && <KnowledgeGapActions topic={topic} />}
          </div>
          <DialogDescription>
            {topic
              ? t("topicSummary", {
                  count: topic.question_count,
                  knowledgeBase: topic.knowledge_base_name,
                })
              : t("nothingAutomatic")}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          {isLoading ? (
            <LoadingState variant="skeleton-list" rows={3} />
          ) : error || !topic ? (
            <ErrorState
              title={t("loadTopicFailed")}
              description={t("loadFailedBody")}
              cta={{ label: t("retry"), onClick: () => void refetch() }}
            />
          ) : (
            <>
              <KnowledgeGapDraftPanel topic={topic} />
              <h3 className="text-foreground text-sm font-semibold">{t("questions")}</h3>
              <ul className="space-y-3">
                {topic.questions.map((question) => (
                  <KnowledgeGapQuestionItem key={question.search_id} question={question} />
                ))}
              </ul>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
