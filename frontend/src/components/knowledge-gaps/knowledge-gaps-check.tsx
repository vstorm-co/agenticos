"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useClassifyKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { useOrganizations } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

interface CheckProps {
  knowledgeBaseId: string;
  /** Recent answers no model has read for gaps yet. */
  unchecked: number;
}

/**
 * Have a model read a knowledge base's recent answers for questions it could not answer.
 *
 * Offered only where it can run: AI assistance on, somebody who may change the
 * knowledge base (the caller decides that) and run the classifier, and answers
 * waiting to be read.
 */
export function CheckAnswersButton({ knowledgeBaseId, unchecked }: CheckProps) {
  const t = useTranslations("knowledgeGaps");
  const { activeOrg } = useOrganizations();
  const { can } = usePermissions();
  const check = useClassifyKnowledgeGaps(knowledgeBaseId);
  if (activeOrg?.ai_assistance_enabled !== true || !can(Perm.agentsRun) || unchecked === 0) {
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

/**
 * Why no check is offered while AI assistance is off, with the way to the switch
 * for somebody who may turn it on.
 */
export function CheckAnswersAiOff({ unchecked }: Pick<CheckProps, "unchecked">) {
  const t = useTranslations("knowledgeGaps");
  const { activeOrg } = useOrganizations();
  const { can } = usePermissions();
  if (!activeOrg || activeOrg.ai_assistance_enabled === true || unchecked === 0) return null;
  return (
    <p className="border-border bg-muted/40 text-muted-foreground border-b px-4 py-2 text-xs sm:px-5">
      {t("uncheckedAiOff", { count: unchecked })}{" "}
      {can(Perm.orgSettings) ? (
        <Link href={ROUTES.ORG_MEMBERS(activeOrg.id)} className="font-medium underline">
          {t("enableAi")}
        </Link>
      ) : (
        t("askAdmin")
      )}
    </p>
  );
}
