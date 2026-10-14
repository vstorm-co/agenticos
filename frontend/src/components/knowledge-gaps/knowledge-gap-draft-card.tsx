"use client";

import Link from "next/link";
import { Download, FileText, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { Alert, AlertDescription, AlertTitle, Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { saveBlob } from "@/lib/file-access";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapDraft } from "@/types/knowledge-gaps";

function asMarkdown(title: string, content: string): string {
  return `# ${title}\n\n${content}\n`;
}

/**
 * A drafted passage, labelled as one, with the sources it was checked against.
 *
 * Offered only to copy or download: nothing here adds it to the collection,
 * because a person checks the facts and adds the document.
 */
export function KnowledgeGapDraftCard({ draft }: { draft: KnowledgeGapDraft }) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const markdown = asMarkdown(draft.title, draft.content);

  return (
    <Alert>
      <AlertTitle className="space-y-1">
        <Badge variant="outline">{t("draftLabel")}</Badge>
        <span className="block">{draft.title}</span>
      </AlertTitle>
      <AlertDescription className="space-y-2">
        <p className="text-xs">{t("draftNotice")}</p>
        <p className="text-foreground text-sm whitespace-pre-wrap">{draft.content}</p>
        {draft.sources.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label={t("draftSources")}>
            {draft.sources.map((source) => (
              <li key={`${source.kind}:${source.id}`}>
                <Badge variant="secondary" className="max-w-xs">
                  {source.kind === "document" ? (
                    <FileText className="h-3 w-3" aria-hidden />
                  ) : (
                    <MessageSquare className="h-3 w-3" aria-hidden />
                  )}
                  <span className="truncate">{source.label}</span>
                </Badge>
              </li>
            ))}
          </ul>
        )}
        {draft.unverified > 0 && (
          <p className="text-xs">{t("draftUnverified", { count: draft.unverified })}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span>{timeAgo(draft.drafted_at, tTime, locale)}</span>
          {draft.run_id && (
            <Link href={`${ROUTES.RUNS}?run=${draft.run_id}`} className="underline">
              {t("openDraftRun")}
            </Link>
          )}
          <CopyButton text={markdown} className="opacity-100" />
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() =>
              saveBlob(new Blob([markdown], { type: "text/markdown" }), "knowledge-gap-draft.md")
            }
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {t("downloadDraft")}
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
