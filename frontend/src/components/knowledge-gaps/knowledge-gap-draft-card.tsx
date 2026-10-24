"use client";

import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Alert, AlertDescription, AlertTitle, Badge } from "@/components/ui";
import type { KnowledgeGapDraft } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftMeta } from "./knowledge-gap-draft-meta";

/**
 * A topic's content, labelled as a draft, for somebody who may read the topic but
 * not change its knowledge base: whoever may change it edits and adds it. A model
 * may have written it from other people's questions, so an image in it is drawn
 * as a link rather than fetched.
 */
export function KnowledgeGapDraftCard({ draft }: { draft: KnowledgeGapDraft }) {
  const t = useTranslations("knowledgeGaps");
  return (
    <Alert>
      <AlertTitle className="space-y-1">
        <Badge variant="outline">{t("draftLabel")}</Badge>
        <span className="block">{draft.title}</span>
      </AlertTitle>
      <AlertDescription className="space-y-2">
        <p className="text-xs">{t("draftNotice")}</p>
        <div className="text-foreground text-sm">
          <MarkdownContent content={draft.content} inertImages />
        </div>
        <KnowledgeGapDraftMeta draft={draft} />
      </AlertDescription>
    </Alert>
  );
}
