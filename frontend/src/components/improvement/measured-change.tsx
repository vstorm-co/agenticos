"use client";

import { useTranslations } from "next-intl";
import { ChangePreview } from "@/components/authoring/result-dialog";
import type { EvidenceSource, Hunk } from "@/types/authoring";
import { StateBadge } from "./widgets";

/**
 * A change as it was measured and accepted: a person's rewording replaces the
 * helper's text, so a decided session shows what went into the agent.
 */
export function measuredHunk(hunk: Hunk): Hunk {
  const text = hunk.accepted_text ?? hunk.edited_text;
  return text ? { ...hunk, new_text: text } : hunk;
}

export function reworded(hunk: Hunk): boolean {
  return (
    Boolean(hunk.edited_text) ||
    (hunk.accepted_text != null && hunk.accepted_text !== hunk.new_text)
  );
}

/** One change with the text it was measured with, marked when a person reworded it. */
export function MeasuredChange({
  hunk,
  sources,
}: {
  hunk: Hunk;
  sources: Record<string, EvidenceSource>;
}) {
  const t = useTranslations("improvement.attemptChanges");
  return (
    <div className="space-y-2">
      {reworded(hunk) && (
        <div className="space-y-1">
          <StateBadge tone="neutral">{t("edited")}</StateBadge>
          <p className="text-muted-foreground text-xs">{t("editedReason")}</p>
        </div>
      )}
      <ChangePreview hunk={measuredHunk(hunk)} sources={sources} />
    </div>
  );
}
