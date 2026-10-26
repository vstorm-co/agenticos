"use client";

import { useLocale, useTranslations } from "next-intl";
import type { ImprovementStep } from "@/lib/improvement-steps";
import type { Improvement } from "@/types/improvement";

/** Which step each decision a person can make belongs to, and the message that words it. */
const DECISIONS: Record<string, [ImprovementStep, string]> = {
  "improvement.started": ["understand", "started"],
  "improvement.evidence_decided": ["understand", "evidence_decided"],
  "improvement.selection_confirmed": ["changes", "selection_confirmed"],
  "improvement.round_selected": ["result", "round_selected"],
  "improvement.attribution_started": ["result", "attribution_started"],
  "improvement.knowledge_check_started": ["result", "knowledge_check_started"],
  "improvement.review_recomputed": ["result", "review_recomputed"],
  "improvement.continuation_confirmed": ["result", "continuation_confirmed"],
  "improvement.retried": ["result", "retried"],
  "improvement.discarded": ["result", "discarded"],
  "improvement.accepted": ["accept", "accepted"],
  "improvement.published": ["accept", "published"],
};

/** The people who decided something on this step, newest last, when their names may be shown. */
export function StepDecisions({ session, step }: { session: Improvement; step: ImprovementStep }) {
  const t = useTranslations("improvement.decided");
  const locale = useLocale();
  const decided = session.timeline.filter(
    (event) => event.actor_name && DECISIONS[event.action]?.[0] === step,
  );
  if (decided.length === 0) return null;
  return (
    <section className="space-y-1 text-sm" aria-label={t("title")}>
      <h3 className="text-muted-foreground text-xs font-medium">{t("title")}</h3>
      <ul className="text-muted-foreground space-y-1">
        {decided.map((event, index) => (
          <li key={`${event.action}:${event.at}:${index}`}>
            {t(DECISIONS[event.action]![1], {
              name: event.actor_name!,
              at: new Date(event.at).toLocaleString(locale),
            })}
          </li>
        ))}
      </ul>
    </section>
  );
}
