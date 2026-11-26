"use client";

import Link from "next/link";
import { BookText, FileText, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useInImproveWizard } from "./wizard-mode";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapDraft, KnowledgeGapSource } from "@/types/knowledge-gaps";

const SOURCE_ICON: Record<KnowledgeGapSource["kind"], typeof FileText> = {
  document: FileText,
  question: MessageSquare,
  context: BookText,
};

/**
 * Verified sources and the run that wrote the draft. Creation time belongs to its header.
 */
export function KnowledgeGapDraftMeta({ draft }: { draft: KnowledgeGapDraft }) {
  const wizard = useInImproveWizard();
  const t = useTranslations("knowledgeGaps");

  if (draft.sources.length === 0 && draft.unverified === 0 && (wizard || draft.run_id === null))
    return null;
  return (
    <div className="space-y-2">
      {draft.sources.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={t("draftSources")}>
          {draft.sources.map((source) => {
            const Icon = SOURCE_ICON[source.kind];
            return (
              <li key={`${source.kind}:${source.id}`} className="max-w-full min-w-0">
                <Badge variant="secondary" className="max-w-full sm:max-w-xs">
                  <Icon className="h-3 w-3" aria-hidden />
                  <span className="truncate">{source.label}</span>
                </Badge>
              </li>
            );
          })}
        </ul>
      )}
      {draft.unverified > 0 && (
        <p className="text-xs">{t("draftUnverified", { count: draft.unverified })}</p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {draft.run_id && !wizard && (
          <Link href={`${ROUTES.RUNS}?run=${draft.run_id}`} className="underline">
            {t("openDraftRun")}
          </Link>
        )}
      </div>
    </div>
  );
}

/** Label the draft's own timestamp rather than leaving a bare age beneath its actions. */
export function KnowledgeGapDraftTime({ draft }: { draft: KnowledgeGapDraft }) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  return (
    <time dateTime={draft.drafted_at} className="text-muted-foreground block text-xs">
      {t("draftCreated", { time: timeAgo(draft.drafted_at, tTime, locale) })}
    </time>
  );
}
