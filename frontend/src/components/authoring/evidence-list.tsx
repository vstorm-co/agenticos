"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import type { EvidenceItem } from "@/types/authoring";

/**
 * What a suggestion rests on: each quote linked to the run it is from.
 *
 * Every item here was checked against that run before it was kept; the count of
 * those that were not says something was removed. A reader without `runs:view`
 * gets the links without the words.
 */
export function EvidenceList({ items, dropped }: { items: EvidenceItem[]; dropped: number }) {
  const t = useTranslations("authoring.evidence");
  if (items.length === 0 && dropped === 0) {
    return <p className="text-muted-foreground text-xs">{t("none")}</p>;
  }
  return (
    <div className="space-y-1.5">
      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li key={`${item.run_id}-${index}`} className="text-xs">
            {item.quote !== null && <q className="italic">{item.quote}</q>}{" "}
            <Link
              href={`${ROUTES.RUNS}?run=${item.run_id}`}
              className="text-muted-foreground font-mono underline"
            >
              {t("run", { id: item.run_id.slice(0, 8) })}
            </Link>
          </li>
        ))}
      </ul>
      {dropped > 0 && (
        <p className="text-muted-foreground text-xs">{t("dropped", { count: dropped })}</p>
      )}
    </div>
  );
}

/** The Improve wizard's "Based on": each quote with the conversation it is from, never a run id. */
export function ConversationEvidence({
  items,
  conversations,
}: {
  items: EvidenceItem[];
  conversations: Record<string, string | null>;
}) {
  const t = useTranslations("improvement");
  if (items.length === 0)
    return <p className="text-muted-foreground text-xs">{t("basedOnNone")}</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => {
        const conversation = conversations[item.run_id];
        return (
          <li key={`${item.run_id}-${index}`} className="text-xs">
            {item.quote !== null && <q className="italic">{item.quote}</q>}{" "}
            {conversation && (
              <Link href={`/chat/${conversation}`} className="text-muted-foreground underline">
                {t("openConversation")}
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}
