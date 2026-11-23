"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { BookCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useInImproveWizard } from "./wizard-mode";

import { Alert, AlertDescription } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type {
  KnowledgeGapDocument,
  KnowledgeGapDraft,
  KnowledgeGapTopicDetail,
} from "@/types/knowledge-gaps";
import { KnowledgeGapDraftTime } from "./knowledge-gap-draft-meta";
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
export function KnowledgeGapDraftPanel({
  topic,
  onDirtyChange,
}: {
  topic: KnowledgeGapTopicDetail;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [dirty, setDirty] = useState(false);
  const changed = useCallback(
    (value: boolean) => {
      setDirty(value);
      onDirtyChange?.(value);
    },
    [onDirtyChange],
  );
  const t = useTranslations("knowledgeGaps");
  const { can } = usePermissions();
  const wizard = useInImproveWizard();
  const mayDraft = topic.can_edit && can(Perm.agentsRun);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-1">
          <h3 className="hidden text-sm font-medium lg:block">{t("workspace.draft")}</h3>
          {topic.draft && <KnowledgeGapDraftTime draft={topic.draft} />}
        </div>
        <KnowledgeGapDraftStatus topic={topic} editable={mayDraft} offerRedraft disabled={dirty} />
      </div>
      {dirty && topic.status !== "covered" && (
        <p role="status" className="text-muted-foreground text-xs">
          {t("workspace.unsaved")}
        </p>
      )}
      {wizard && mayDraft && topic.draft && !topic.drafting && (
        <p className="text-muted-foreground text-xs">{t("draftAgainInSession")}</p>
      )}
      {topic.covered_by && (
        <CoveredBy knowledgeBaseId={topic.knowledge_base_id} document={topic.covered_by} />
      )}
      {topic.draft?.already_covered && <AlreadyCovered draft={topic.draft} />}
      {topic.can_edit && topic.status === "open" ? (
        <KnowledgeGapEditor
          key={topic.draft?.drafted_at ?? "new"}
          topic={topic}
          onDirtyChange={changed}
        />
      ) : (
        topic.draft && (
          <KnowledgeGapDraftCard
            draft={topic.draft}
            addedTo={
              topic.status === "covered" && topic.covered_by ? topic.knowledge_base_name : null
            }
          />
        )
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
