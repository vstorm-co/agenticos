"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useClassifyKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";

interface CheckProps {
  knowledgeBaseId: string;
  /** Recent answers no model has read for gaps yet. */
  unchecked: number;
}

/**
 * Have a model read a knowledge base's recent answers for questions it could not answer.
 *
 * Offered to somebody who may change the knowledge base (the caller decides
 * that) and run the classifier, with answers
 * waiting to be read.
 */
export function CheckAnswersButton({ knowledgeBaseId, unchecked }: CheckProps) {
  const t = useTranslations("knowledgeGaps");
  const { can } = usePermissions();
  const check = useClassifyKnowledgeGaps(knowledgeBaseId);
  if (!can(Perm.agentsRun) || unchecked === 0) {
    return null;
  }
  return (
    <Button
      variant="outline"
      size="sm"
      title={t("checkAnswersHint")}
      data-tour="kb-gaps-check"
      disabled={check.isPending}
      onClick={() => check.mutate()}
    >
      <Sparkles className="h-3.5 w-3.5" aria-hidden />
      {t("checkAnswers", { count: unchecked })}
    </Button>
  );
}
