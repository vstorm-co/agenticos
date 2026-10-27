"use client";

import { useLocale, useTranslations } from "next-intl";
import type { ImprovementStep } from "@/lib/improvement-steps";
import type { Improvement } from "@/types/improvement";

/** Which step each decision a person can make belongs to, and the message that words it. */
const DECISIONS: Record<string, [ImprovementStep, string]> = {
  "improvement.started": ["understand", "started"],
  "improvement.selection_confirmed": ["changes", "selection_confirmed"],
  "improvement.changes_chosen": ["changes", "selection_confirmed"],
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

type Event = Improvement["timeline"][number];

/**
 * Where a decision belongs. Next step is pressed at a stop and recorded at its
 * stage, so it belongs to the step that stopped: Changes after filtering,
 * otherwise Understand.
 */
function placeOf(event: Event): [ImprovementStep, string] | undefined {
  if (event.action === "improvement.next_step_taken")
    return event.stage === "filtering"
      ? ["changes", "nextStepCheck"]
      : ["understand", "nextStepPropose"];
  return DECISIONS[event.action];
}

/** The people who decided something on this step, newest last, when their names may be shown. */
export function StepDecisions({ session, step }: { session: Improvement; step: ImprovementStep }) {
  const t = useTranslations("improvement.decided");
  const locale = useLocale();
  const decided = session.timeline.filter(
    (event) => event.actor_name && placeOf(event)?.[0] === step,
  );
  if (decided.length === 0) return null;
  return (
    <section className="space-y-1 text-sm" aria-label={t("title")}>
      <h3 className="text-muted-foreground text-xs font-medium">{t("title")}</h3>
      <ul className="text-muted-foreground space-y-1">
        {decided.map((event, index) => (
          <li key={`${event.action}:${event.at}:${index}`}>
            {t(placeOf(event)![1], {
              name: event.actor_name!,
              at: new Date(event.at).toLocaleString(locale),
            })}
          </li>
        ))}
      </ul>
    </section>
  );
}
