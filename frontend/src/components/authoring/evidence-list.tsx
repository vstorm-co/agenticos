"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import type { EvidenceItem, EvidenceSource } from "@/types/authoring";

/**
 * The label a quote's run was read under - "test question 2", "conversation 1".
 * Evidence kept before labels existed is numbered by its place in the list, and
 * is a test question only when the run is known to be one.
 */
function labelOf(item: EvidenceItem, index: number, source?: EvidenceSource) {
  return {
    kind: item.source ?? (source?.kind === "train_eval" ? "test_question" : "conversation"),
    number: item.number ?? index + 1,
  };
}

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
        {items.map((item, index) => {
          const { kind, number } = labelOf(item, index);
          return (
            <li key={`${item.run_id}-${index}`} className="text-xs">
              {item.quote !== null && <q className="italic">{item.quote}</q>}{" "}
              <Link
                href={`${ROUTES.RUNS}?run=${item.run_id}`}
                className="text-muted-foreground underline"
              >
                {t(kind === "test_question" ? "testQuestion" : "conversation", { number })}
              </Link>
            </li>
          );
        })}
      </ul>
      {dropped > 0 && (
        <p className="text-muted-foreground text-xs">{t("dropped", { count: dropped })}</p>
      )}
    </div>
  );
}

/**
 * The Improve wizard's "Based on": each quote with where it came from - a test
 * question or a conversation, and what was asked - never a run id.
 */
export function ConversationEvidence({
  items,
  sources,
}: {
  items: EvidenceItem[];
  sources: Record<string, EvidenceSource>;
}) {
  const t = useTranslations("improvement");
  if (items.length === 0)
    return <p className="text-muted-foreground text-xs">{t("basedOnNone")}</p>;
  return (
    <ul className="space-y-2">
      {items.map((item, index) => {
        const known = sources[item.run_id];
        const { kind, number } = labelOf(item, index, known);
        const conversation = known?.conversation_id;
        const values = {
          kind,
          number,
          source: (chunks: ReactNode) =>
            conversation ? (
              <Link href={`/chat/${conversation}`} className="underline">
                {chunks}
              </Link>
            ) : (
              <span className="font-medium">{chunks}</span>
            ),
        };
        return (
          <li key={`${item.run_id}-${index}`} className="space-y-0.5 text-xs">
            {item.quote !== null && <q className="block italic">{item.quote}</q>}
            <p className="text-muted-foreground line-clamp-2 break-words">
              {known?.question
                ? t.rich("basedOnSourceAsked", { ...values, question: known.question })
                : t.rich("basedOnSource", values)}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

/** A full run id, or the eight characters a model abbreviates one to after "run". */
const RUN_REFERENCE =
  /\b(?:runs?\s+)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{8})\b/gi;

/**
 * A rationale as written, with the run ids a model put in it shown as links
 * labelled the way "Based on" lists them - or as "a conversation" for one it
 * does not list. The stored text is not changed.
 */
export function RationaleText({
  text,
  evidence,
  conversations,
}: {
  text: string;
  evidence: EvidenceItem[];
  /** In the Improve wizard: each evidence run's conversation, linked instead of the run. */
  conversations?: Record<string, string | null>;
}) {
  const t = useTranslations("authoring.evidence");
  const parts: ReactNode[] = [];
  let from = 0;
  for (const match of text.matchAll(RUN_REFERENCE)) {
    const id = match[1]!.toLowerCase();
    const index = evidence.findIndex((item) => item.run_id.toLowerCase().startsWith(id));
    if (index < 0 && id.length < 36) continue;
    parts.push(text.slice(from, match.index));
    from = match.index + match[0].length;
    if (index < 0) {
      parts.push(t("aConversation"));
      continue;
    }
    const item = evidence[index]!;
    const { kind, number } = labelOf(item, index);
    const conversation = conversations?.[item.run_id];
    parts.push(
      <Link
        key={match.index}
        className="underline underline-offset-2"
        href={conversation ? `/chat/${conversation}` : `${ROUTES.RUNS}?run=${item.run_id}`}
      >
        {t(kind === "test_question" ? "testQuestion" : "conversation", { number })}
      </Link>,
    );
  }
  parts.push(text.slice(from));
  return <p className="text-sm">{parts}</p>;
}
