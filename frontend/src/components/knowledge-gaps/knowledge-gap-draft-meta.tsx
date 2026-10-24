"use client";

import Link from "next/link";
import { BookText, Download, FileText, MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { useAgentsOfKind } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { saveBlob } from "@/lib/file-access";
import { timeAgo } from "@/lib/utils";
import type { KnowledgeGapDraft, KnowledgeGapSource } from "@/types/knowledge-gaps";
import { Perm } from "@/types/permissions";

/** The `system_key` of the drafter the platform seeds. */
const DRAFTER_KEY = "knowledge_gap_drafter";

const SOURCE_ICON: Record<KnowledgeGapSource["kind"], typeof FileText> = {
  document: FileText,
  question: MessageSquare,
  context: BookText,
};

function asMarkdown(title: string, content: string): string {
  return `# ${title}\n\n${content}\n`;
}

/**
 * What a draft rests on and where it came from: its verified sources, when and by
 * which run it was written, and copying or downloading it. Somebody who may edit
 * the drafter is pointed at its instructions, which decide how the next draft reads.
 */
export function KnowledgeGapDraftMeta({ draft }: { draft: KnowledgeGapDraft }) {
  const t = useTranslations("knowledgeGaps");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const markdown = asMarkdown(draft.title, draft.content);
  const { can } = usePermissions();
  const { agents } = useAgentsOfKind("drafter", { enabled: can(Perm.agentsView) });
  const drafter = agents.find((agent) => agent.system_key === DRAFTER_KEY);

  return (
    <div className="space-y-2">
      {draft.sources.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={t("draftSources")}>
          {draft.sources.map((source) => {
            const Icon = SOURCE_ICON[source.kind];
            return (
              <li key={`${source.kind}:${source.id}`}>
                <Badge variant="secondary" className="max-w-xs">
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
        <span>{timeAgo(draft.drafted_at, tTime, locale)}</span>
        {draft.run_id && (
          <Link href={`${ROUTES.RUNS}?run=${draft.run_id}`} className="underline">
            {t("openDraftRun")}
          </Link>
        )}
        {drafter?.can_edit && (
          <Link href={ROUTES.AGENT_DETAIL(drafter.id)} className="underline">
            {t("editDrafter")}
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
    </div>
  );
}
