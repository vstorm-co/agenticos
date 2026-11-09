"use client";

import { useTranslations } from "next-intl";
import { InImproveWizard } from "./wizard-mode";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { DIALOG_BODY, DIALOG_FILL, DIALOG_BROAD } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { KnowledgeGapActions } from "./knowledge-gap-actions";
import { KnowledgeGapDraftPanel } from "./knowledge-gap-draft";
import { KnowledgeGapQuestionItem } from "./knowledge-gap-question";

interface KnowledgeGapDialogProps {
  topicId: string;
  onClose: () => void;
  /** Opened from the Improve wizard: no links out of it. */
  wizard?: boolean;
}

/** A topic's questions, newest first, with what each search found and what to do about it. */
export function KnowledgeGapDialog({ topicId, onClose, wizard = false }: KnowledgeGapDialogProps) {
  const t = useTranslations("knowledgeGaps");
  const { topic, isLoading, error, refetch } = useKnowledgeGap(topicId);

  return (
    <InImproveWizard.Provider value={wizard}>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={cn(DIALOG_BROAD, DIALOG_FILL)}>
          <DialogHeader>
            <div className="flex items-start justify-between gap-2">
              <DialogTitle className="break-words">{topic?.label ?? t("topic")}</DialogTitle>
              {topic && <KnowledgeGapActions topic={topic} />}
            </div>
            <DialogDescription>
              {topic
                ? t("topicSummary", {
                    count: topic.question_count,
                    askers: topic.asker_count,
                    knowledgeBase: topic.knowledge_base_name,
                  })
                : t("nothingAutomatic")}
            </DialogDescription>
          </DialogHeader>
          <div className={cn(DIALOG_BODY, "space-y-4")}>
            {isLoading ? (
              <LoadingState variant="skeleton-list" rows={3} />
            ) : error || !topic ? (
              <ErrorState
                title={t("loadTopicFailed")}
                description={t("loadFailedBody")}
                cta={{ label: t("retry"), onClick: () => void refetch() }}
              />
            ) : (
              <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
                <div className="min-w-0">
                  <KnowledgeGapDraftPanel topic={topic} />
                </div>
                <section className="min-w-0 space-y-3 rounded-xl border p-4">
                  <h3 className="text-foreground text-sm font-semibold">{t("questions")}</h3>
                  <ul className="space-y-3">
                    {topic.questions.map((question) => (
                      <KnowledgeGapQuestionItem key={question.search_id} question={question} />
                    ))}
                  </ul>
                </section>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </InImproveWizard.Provider>
  );
}
