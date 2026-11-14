"use client";

import { useTranslations } from "next-intl";
import { MarkdownContent } from "@/components/chat/markdown-content";

/** A preview of the same messages already readable in Activity. */
export function DatasetSourcePreview({ question, answer }: { question: string; answer: string }) {
  const t = useTranslations("datasets");
  return (
    <details className="rounded-lg border">
      <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
        {t("viewSourceMessages")}
      </summary>
      <div className="space-y-3 border-t p-3">
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs font-medium">{t("sourceUserMessage")}</p>
          <p className="max-h-28 scrollbar-thin overflow-y-auto text-sm break-words whitespace-pre-wrap">
            {question}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs font-medium">{t("sourceAgentAnswer")}</p>
          <div className="max-h-40 scrollbar-thin overflow-y-auto text-sm break-words">
            <MarkdownContent content={answer} inertImages />
          </div>
        </div>
      </div>
    </details>
  );
}
