"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { InImproveWizard } from "./wizard-mode";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CANVAS } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
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
  const [dirty, setDirty] = useState(false);
  const [discard, setDiscard] = useState(false);
  const close = () => (dirty && topic?.status !== "covered" ? setDiscard(true) : onClose());
  const { topic, isLoading, error, refetch } = useKnowledgeGap(topicId);

  return (
    <InImproveWizard.Provider value={wizard}>
      <Dialog open onOpenChange={(open) => !open && close()}>
        <DialogContent className={cn(DIALOG_CANVAS, DIALOG_COLUMN)}>
          <DialogHeader>
            <div className="flex items-start justify-between gap-2">
              <DialogTitle className="break-words">{topic?.label ?? t("topic")}</DialogTitle>
              {topic && <KnowledgeGapActions topic={topic} />}
            </div>
            <DialogDescription>
              {topic ? <TopicSummary topic={topic} /> : t("nothingAutomatic")}
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
              <Tabs defaultValue="draft" activationMode="manual" className="min-w-0">
                <TabsList aria-label={t("topic")} className="mb-4 lg:hidden">
                  <TabsTrigger value="draft">{t("workspace.draft")}</TabsTrigger>
                  <TabsTrigger value="evidence">
                    {t("workspace.evidence", { count: topic.questions.length })}
                  </TabsTrigger>
                </TabsList>
                <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                  <TabsContent
                    value="draft"
                    forceMount
                    className="m-0 min-w-0 lg:data-[state=inactive]:block"
                  >
                    <KnowledgeGapDraftPanel topic={topic} onDirtyChange={setDirty} />
                  </TabsContent>
                  <TabsContent
                    value="evidence"
                    forceMount
                    className="m-0 min-w-0 lg:data-[state=inactive]:block"
                  >
                    <section
                      className="min-w-0 space-y-3 lg:border-l lg:pl-6"
                      aria-label={t("questions")}
                    >
                      <h3 className="text-foreground text-sm font-medium">
                        {t("workspace.evidence", { count: topic.questions.length })}
                      </h3>
                      <ul className="divide-y">
                        {topic.questions.map((question) => (
                          <KnowledgeGapQuestionItem key={question.search_id} question={question} />
                        ))}
                      </ul>
                    </section>
                  </TabsContent>
                </div>
              </Tabs>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={discard}
        onOpenChange={setDiscard}
        title={t("workspace.discardTitle")}
        description={t("workspace.discardBody")}
        confirmLabel={t("workspace.discard")}
        cancelLabel={t("workspace.keepEditing")}
        onConfirm={onClose}
      />
    </InImproveWizard.Provider>
  );
}

/** How often a topic came up: people's questions, and test questions apart, which nobody asked. */
function TopicSummary({ topic }: { topic: KnowledgeGapTopic }) {
  const t = useTranslations("knowledgeGaps");
  const tests = topic.test_question_count ?? 0;
  const asked = topic.question_count - tests;
  if (asked === 0)
    return t("topicSummaryTests", { count: tests, knowledgeBase: topic.knowledge_base_name });
  return t(tests === 0 ? "topicSummary" : "topicSummaryMixed", {
    count: asked,
    askers: topic.asker_count,
    tests,
    knowledgeBase: topic.knowledge_base_name,
  });
}
