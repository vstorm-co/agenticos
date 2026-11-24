"use client";

import { useTranslations } from "next-intl";

import type { KnowledgeFinding } from "@/types/scoring";

/**
 * What a judge that searches found in the graded agent's knowledge bases: the
 * facts it checked the answer against where no reference answer stated them.
 * Nothing when it found nothing, or did not search.
 */
export function KnowledgeFindings({ findings }: { findings: KnowledgeFinding[] }) {
  const t = useTranslations("datasets.scoring");
  if (findings.length === 0) return null;
  return (
    <div className="mt-2 space-y-1 text-xs">
      <p className="text-muted-foreground font-medium">{t("foundInKnowledge")}</p>
      <ul className="space-y-1.5">
        {findings.map((finding, index) => (
          <li key={index} className="border-l-2 pl-2">
            <p className="text-foreground font-medium break-words">
              {finding.source ?? t("knowledgeDocument")}
            </p>
            <q className="text-muted-foreground block break-words whitespace-pre-wrap">
              {finding.quote}
            </q>
          </li>
        ))}
      </ul>
    </div>
  );
}
