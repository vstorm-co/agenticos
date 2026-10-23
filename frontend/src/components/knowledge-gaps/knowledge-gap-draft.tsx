"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { EnableAiAssistanceLink } from "@/components/teams/enable-ai-assistance-link";
import { Button } from "@/components/ui";
import { useDraftKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { useOrganizations } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopicDetail } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftCard } from "./knowledge-gap-draft-card";

/**
 * The control that asks a model to draft a topic's missing content, and the draft.
 *
 * Off by default: while the organization has AI assistance switched off there is
 * no control, only why - with the way to the switch for somebody who may turn it
 * on. A draft replaces the topic's, so only somebody who may change its
 * knowledge base is offered one. A draft written earlier stays readable either way.
 */
export function KnowledgeGapDraftPanel({ topic }: { topic: KnowledgeGapTopicDetail }) {
  const t = useTranslations("knowledgeGaps");
  const { activeOrg } = useOrganizations();
  const { can } = usePermissions();
  const draft = useDraftKnowledgeGap();
  const aiOn = activeOrg?.ai_assistance_enabled === true;

  return (
    <section className="space-y-3">
      {!aiOn && activeOrg ? (
        <p className="bg-muted rounded-md px-3 py-2 text-xs">
          {t("aiOff")}{" "}
          {can(Perm.orgSettings) ? (
            <EnableAiAssistanceLink orgId={activeOrg.id}>{t("enableAi")}</EnableAiAssistanceLink>
          ) : (
            t("askAdmin")
          )}
        </p>
      ) : (
        aiOn &&
        topic.can_edit &&
        can(Perm.agentsRun) && (
          <Button
            variant="outline"
            size="sm"
            disabled={draft.isPending}
            onClick={() => draft.mutate(topic.id)}
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden />
            {draft.isPending ? t("drafting") : topic.draft ? t("draftAgain") : t("draftContent")}
          </Button>
        )
      )}
      {topic.draft && <KnowledgeGapDraftCard draft={topic.draft} />}
    </section>
  );
}
