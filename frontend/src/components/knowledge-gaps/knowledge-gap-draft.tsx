"use client";

import Link from "next/link";
import { BookCheck, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, Button } from "@/components/ui";
import { useDraftKnowledgeGap } from "@/hooks/use-knowledge-gaps";
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
import { KnowledgeGapEditor } from "./knowledge-gap-editor";

/**
 * A topic's content: asking a model to draft it, writing or finishing it, and
 * adding it to the knowledge base - or the document that covers it already.
 *
 * Drafting is off while the organization has AI assistance switched off, with
 * why and the way to the switch for somebody who may turn it on; writing and
 * adding work either way. Both change the knowledge base's content, so only
 * somebody who may change that base is offered them. Anybody else reads the
 * draft as a draft.
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
            <Link href={ROUTES.ORG_MEMBERS(activeOrg.id)} className="font-medium underline">
              {t("enableAi")}
            </Link>
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
      {topic.covered_by && (
        <CoveredBy knowledgeBaseId={topic.knowledge_base_id} document={topic.covered_by} />
      )}
      {topic.draft?.already_covered && <AlreadyCovered draft={topic.draft} />}
      {topic.can_edit && topic.status !== "covered" ? (
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
