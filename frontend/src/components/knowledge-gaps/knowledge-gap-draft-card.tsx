"use client";

import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Alert, AlertDescription, AlertTitle, Badge } from "@/components/ui";
import type { KnowledgeGapDraft } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftMeta } from "./knowledge-gap-draft-meta";

/**
 * A topic's content, for somebody it is not open to edit for: a draft waiting for
 * whoever may change the knowledge base, or - once `addedTo` names the knowledge
 * base - the content added to it. It says who wrote it: a model from the questions
 * above, or a person. A model may have written it from other people's questions,
 * so an image in it is drawn as a link rather than fetched.
 */
export function KnowledgeGapDraftCard({
  draft,
  addedTo = null,
}: {
  draft: KnowledgeGapDraft;
  addedTo?: string | null;
}) {
  const t = useTranslations("knowledgeGaps");
  const author = draft.run_id === null ? "person" : "model";
  return (
    <Alert>
      <AlertTitle className="space-y-1">
        <Badge variant="outline">
          {addedTo !== null
            ? t("addedLabel", { knowledgeBase: addedTo })
            : author === "person"
              ? t("personDraftLabel")
              : t("draftLabel")}
        </Badge>
        <span className="block">{draft.title}</span>
      </AlertTitle>
      <AlertDescription className="space-y-2">
        <p className="text-xs">
          {addedTo !== null
            ? t("addedNotice", { author })
            : author === "person"
              ? t("personDraftNotice")
              : t("draftNotice")}
        </p>
        <div className="text-foreground text-sm">
          <MarkdownContent content={draft.content} inertImages />
        </div>
        <KnowledgeGapDraftMeta draft={draft} />
      </AlertDescription>
    </Alert>
  );
}
