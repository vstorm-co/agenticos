"use client";

import Link from "next/link";
import { Download, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { Alert, AlertDescription, AlertTitle, Button } from "@/components/ui";
import { useDraftKnowledgeGap } from "@/hooks/use-knowledge-gaps";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { saveBlob } from "@/lib/file-access";
import { timeAgo } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopicDetail } from "@/types/knowledge-gaps";

function asMarkdown(title: string, content: string): string {
  return `# ${title}\n\n${content}\n`;
}

/**
 * The passage a drafting agent proposed, and the control that asks for one.
 *
 * Labelled a draft and offered only to copy or download: nothing here adds it to
 * the collection, because a person checks the facts and adds the document.
 */
export function KnowledgeGapDraftPanel({ topic }: { topic: KnowledgeGapTopicDetail }) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { can } = usePermissions();
  const draft = useDraftKnowledgeGap();
  const current = topic.draft;
  const mayDraft = can(Perm.agentsRun);

  return (
    <section className="space-y-3">
      {mayDraft && (
        <Button
          variant="outline"
          size="sm"
          disabled={draft.isPending}
          onClick={() => draft.mutate(topic.id)}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
          {draft.isPending ? t("drafting") : current ? t("draftAgain") : t("draftContent")}
        </Button>
      )}
      {current && (
        <Alert>
          <AlertTitle>{t("draftTitle", { title: current.title })}</AlertTitle>
          <AlertDescription className="space-y-2">
            <p className="text-xs">{t("draftNotice")}</p>
            <p className="text-foreground text-sm whitespace-pre-wrap">{current.content}</p>
            {current.sources.length > 0 && (
              <p className="text-xs">
                {t("draftSources", { sources: current.sources.join(", ") })}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span>{timeAgo(current.drafted_at, tTime, locale)}</span>
              {current.run_id && (
                <Link href={`${ROUTES.RUNS}?run=${current.run_id}`} className="underline">
                  {t("openDraftRun")}
                </Link>
              )}
              <CopyButton
                text={asMarkdown(current.title, current.content)}
                className="opacity-100"
              />
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2"
                onClick={() =>
                  saveBlob(
                    new Blob([asMarkdown(current.title, current.content)], {
                      type: "text/markdown",
                    }),
                    "knowledge-gap-draft.md",
                  )
                }
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                {t("downloadDraft")}
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
    </section>
  );
}
