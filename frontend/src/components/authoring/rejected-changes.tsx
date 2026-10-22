"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { AuthoringRequest, RejectedChange } from "@/types/authoring";

/**
 * What the assistant proposed and nothing recorded, and why - a passage it could
 * not find, a tool the agent lacks, a field it may not change.
 *
 * Without it a request that proposed six changes and recorded none looks like a
 * request that found nothing to say. Absent when every change was recorded.
 */
export function RejectedChanges({ report }: { report: AuthoringRequest["report"] }) {
  const t = useTranslations("authoring.rejected");
  const rejected = report?.rejected ?? [];
  if (rejected.length === 0) return null;
  const more = report?.rejected_more ?? 0;
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">
        {t("title", { count: rejected.length + more })}
      </summary>
      <ul className="space-y-3 pt-3">
        {rejected.map((item, index) => (
          <li key={`${item.reason}-${index}`} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{t(`kind.${item.kind}`)}</Badge>
              <span className="text-sm">{t(`reason.${item.reason}`)}</span>
            </div>
            <Proposed item={item} />
          </li>
        ))}
      </ul>
      {more > 0 && (
        <p className="text-muted-foreground pt-2 text-xs">{t("more", { count: more })}</p>
      )}
    </details>
  );
}

function Proposed({ item }: { item: RejectedChange }) {
  const t = useTranslations("authoring.rejected");
  const { change } = item;
  if (item.kind === "finding") {
    return (
      <div className="text-muted-foreground space-y-1 text-xs">
        <p>{change.text}</p>
        {change.edit && (
          <p className="font-mono break-words whitespace-pre-wrap">
            {t("about", { line: change.edit })}
          </p>
        )}
      </div>
    );
  }
  const subject =
    item.kind === "tool_override"
      ? `${change.capability_id} / ${change.tool_id}`
      : item.kind === "spec_field"
        ? `${change.op} ${change.path}`
        : change.old_text || (change.after ? t("after", { passage: change.after }) : t("atEnd"));
  const proposed =
    item.kind === "tool_override"
      ? [change.name, change.description].filter(Boolean).join(" - ")
      : item.kind === "spec_field"
        ? JSON.stringify(change.value ?? null)
        : change.new_text;
  return (
    <div className="text-muted-foreground space-y-1 text-xs">
      <p className="font-mono break-words whitespace-pre-wrap">{subject}</p>
      {proposed && (
        <p className="break-words whitespace-pre-wrap">{t("proposed", { text: proposed })}</p>
      )}
      {change.rationale && <p>{change.rationale}</p>}
    </div>
  );
}
