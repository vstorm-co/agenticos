"use client";

import Link from "next/link";
import { BookCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useInImproveWizard } from "./wizard-mode";

import { EnableAiAssistanceLink } from "@/components/teams/enable-ai-assistance-link";
import { Alert, AlertDescription } from "@/components/ui";
import { useOrganizations } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type {
  KnowledgeGapDocument,
  KnowledgeGapDraft,
  KnowledgeGapTopicDetail,
} from "@/types/knowledge-gaps";
import { KnowledgeGapDraftCard } from "./knowledge-gap-draft-card";
import { KnowledgeGapDraftStatus } from "./knowledge-gap-draft-status";
import { KnowledgeGapEditor } from "./knowledge-gap-editor";

/**
 * A topic's content: asking a model to draft it, writing or finishing it, and
 * adding it to the knowledge base - or the document that covers it already.
 *
 * A draft is written only when somebody asks for one, at the cost shown on the
 * button. Drafting is off while the organization has AI assistance switched off,
 * with why and the way to the switch for somebody who may turn it on; writing
 * and adding work either way. Both change the knowledge base's content, so only
 * somebody who may change that base is offered them. Anybody else reads the
 * draft as a draft.
 */
export function KnowledgeGapDraftPanel({ topic }: { topic: KnowledgeGapTopicDetail }) {
  const t = useTranslations("knowledgeGaps");
  const { activeOrg } = useOrganizations();
  const { can } = usePermissions();
  const aiOn = activeOrg?.ai_assistance_enabled === true;
  const wizard = useInImproveWizard();
  const mayDraft = aiOn && topic.can_edit && can(Perm.agentsRun);

  return (
    <section className="space-y-3">
      {!aiOn && activeOrg && (
        <p className="bg-muted rounded-md px-3 py-2 text-xs">
          {t("aiOff")}{" "}
          {can(Perm.orgSettings) ? (
            <EnableAiAssistanceLink orgId={activeOrg.id}>{t("enableAi")}</EnableAiAssistanceLink>
          ) : (
            t("askAdmin")
          )}
        </p>
      )}
      <KnowledgeGapDraftStatus topic={topic} editable={mayDraft} offerRedraft />
      {wizard && mayDraft && topic.draft && !topic.drafting && (
        <p className="text-muted-foreground text-xs">{t("draftAgainInSession")}</p>
      )}
      {topic.covered_by && (
        <CoveredBy knowledgeBaseId={topic.knowledge_base_id} document={topic.covered_by} />
      )}
      {topic.draft?.already_covered && <AlreadyCovered draft={topic.draft} />}
      {topic.can_edit && topic.status === "open" ? (
        <KnowledgeGapEditor key={topic.draft?.drafted_at ?? "new"} topic={topic} />
      ) : (
        topic.draft && <KnowledgeGapDraftCard draft={topic.draft} />
      )}
    </section>
  );
}

function CoveredBy({
  knowledgeBaseId,
  document,
}: {
  knowledgeBaseId: string;
  document: KnowledgeGapDocument;
}) {
  const t = useTranslations("knowledgeGaps");
  return (
    <Alert variant="info">
      <BookCheck className="h-4 w-4" aria-hidden />
      <AlertDescription>
        {t.rich("coveredBy", {
          name: document.filename,
          link: (chunks) => (
            <Link
              href={`${ROUTES.RAG_DETAIL(knowledgeBaseId)}?tab=documents`}
              className="font-medium underline"
            >
              {chunks}
            </Link>
          ),
        })}
      </AlertDescription>
    </Alert>
  );
}

function AlreadyCovered({ draft }: { draft: KnowledgeGapDraft }) {
  const t = useTranslations("knowledgeGaps");
  const answering = draft.sources
    .filter((source) => source.kind !== "question")
    .map((source) => source.label);
  return (
    <Alert variant="info">
      <AlertDescription>
        {answering.length > 0
          ? t("alreadyCoveredBy", { sources: answering.join(", ") })
          : t("alreadyCovered")}
      </AlertDescription>
    </Alert>
  );
}
