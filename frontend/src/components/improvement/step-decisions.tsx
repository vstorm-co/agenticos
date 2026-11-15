"use client";

import { useLocale, useTranslations } from "next-intl";
import { currentAttempt, type ImprovementStep } from "@/lib/improvement-steps";
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

/** Steps a new attempt runs again, so they show only what was decided in it. */
const PER_ATTEMPT: readonly ImprovementStep[] = ["changes", "check"];
/** How long after an attempt began the Try again that began it is recorded. */
const SAME_REQUEST_MS = 60_000;

/** The note a Try again left for the attempt it started, when it left one. */
function noteOf(session: Improvement, event: Event): string | null {
  const started = session.iterations.find(
    (round) => Math.abs(Date.parse(round.started_at) - Date.parse(event.at)) < SAME_REQUEST_MS,
  );
  return started?.note ?? null;
}

/** The people who decided something on this step, newest last, when their names may be shown. */
export function StepDecisions({ session, step }: { session: Improvement; step: ImprovementStep }) {
  const t = useTranslations("improvement.decided");
  const locale = useLocale();
  const attempt = currentAttempt(session);
  const since =
    attempt && attempt.number > 1 && PER_ATTEMPT.includes(step)
      ? Date.parse(attempt.started_at)
      : null;
  const decided = session.timeline.filter(
    (event) =>
      event.actor_name &&
      placeOf(event)?.[0] === step &&
      (since === null || Date.parse(event.at) >= since),
  );
  const askedAgain =
    step === "changes" && since !== null
      ? session.timeline.findLast(
          (event) =>
            event.action === "improvement.continuation_confirmed" &&
            event.actor_name &&
            Math.abs(Date.parse(event.at) - since) < SAME_REQUEST_MS,
        )
      : undefined;
  if (decided.length === 0 && !askedAgain) return null;
  return (
    <section className="space-y-1 text-sm" aria-label={t("title")}>
      <h3 className="text-muted-foreground text-xs font-medium">{t("title")}</h3>
      <ul className="text-muted-foreground space-y-1">
        {askedAgain && (
          <li>
            {t("askedAgain", {
              name: askedAgain.actor_name!,
              at: new Date(askedAgain.at).toLocaleString(locale),
              noted: attempt?.note ? "yes" : "no",
              note: attempt?.note ?? "",
            })}
          </li>
        )}
        {decided.map((event, index) => {
          const note =
            event.action === "improvement.continuation_confirmed" && noteOf(session, event);
          return (
            <li key={`${event.action}:${event.at}:${index}`}>
              {t(placeOf(event)![1], {
                name: event.actor_name!,
                at: new Date(event.at).toLocaleString(locale),
                noted: note ? "yes" : "no",
                note: note || "",
              })}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
