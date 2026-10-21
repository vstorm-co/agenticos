"use client";

import { CheckCircle2, MinusCircle, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import type { VerifyFinding } from "@/types/authoring";
import { EvidenceList } from "./evidence-list";

const ICONS = {
  supports: CheckCircle2,
  risk: TriangleAlert,
  removed: MinusCircle,
} as const;

/**
 * What the assistant made of a person's own edits: what the evidence supports,
 * what it risks, and what the edit dropped. It informs and blocks nothing - the
 * changes it suggests wait with the others.
 */
export function VerifyReport({ findings }: { findings: VerifyFinding[] }) {
  const t = useTranslations("authoring.verify");
  if (findings.length === 0) return <p className="text-muted-foreground text-sm">{t("nothing")}</p>;
  return (
    <ul className="space-y-3">
      {findings.map((finding, index) => {
        const Icon = ICONS[finding.verdict];
        return (
          <li key={`${finding.verdict}-${index}`} className="flex gap-2">
            <Icon
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-label={t(`verdict.${finding.verdict}`)}
            />
            <div className="space-y-1">
              <p className="text-sm">{finding.text}</p>
              <EvidenceList
                items={finding.evidence.map((item) => ({
                  run_id: item.run_id,
                  quote: item.quote ?? null,
                }))}
                dropped={finding.evidence_dropped}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
