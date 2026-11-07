"use client";

import { useTranslations } from "next-intl";
import { useAttemptChanges, useImprovementEvidence } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { MeasuredChange } from "./measured-change";
import { StateBadge } from "./widgets";

/**
 * What each attempt proposed and what its check came to, read once the session has
 * moved past Changes: the latest attempt open, the earlier ones folded.
 */
export function TriedChanges({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const tried = [...session.iterations].sort((a, b) => b.number - a.number);
  return (
    <section className="min-w-0 space-y-3">
      <h2 className="font-medium">{t("triedChanges")}</h2>
      {tried.map((round, index) => {
        const heldBack = round.number > session.max_iterations;
        return (
          <details key={round.id} open={index === 0} className="rounded-xl border p-4">
            <summary className="cursor-pointer text-sm font-medium">
              {heldBack
                ? t("heldBack")
                : t("triedAttempt", {
                    number: round.number,
                    verdict: round.verdict ?? (round.batch_id ? "unmeasured" : "none"),
                    dropped: round.dropped.length,
                  })}
            </summary>
            {round.batch_id && !heldBack && <AttemptProposals session={session} round={round} />}
          </details>
        );
      })}
    </section>
  );
}

function AttemptProposals({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement.attemptChanges");
  const tErrors = useTranslations("errors");
  const { changes, isLoading, error } = useAttemptChanges(
    session.agent_id,
    session.id,
    round.number,
  );
  const { evidence } = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const sources = Object.fromEntries((evidence?.items ?? []).map((item) => [item.run_id, item]));
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("loading")}</p>;
  if (changes.length === 0) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  const tested = round.included_hunk_ids;
  return (
    <div className="mt-3 space-y-4">
      {changes.map((hunk) => (
        <div key={hunk.id} className="space-y-2">
          <StateBadge tone="neutral">
            {t(!tested || tested.includes(hunk.id) ? "tested" : "notTested", {
              number: round.number,
            })}
          </StateBadge>
          <MeasuredChange hunk={hunk} sources={sources} />
        </div>
      ))}
    </div>
  );
}

/** The changes an attempt tested, as measured, for the person about to accept them. */
export function AcceptedChanges({
  session,
  round,
}: {
  session: Improvement;
  round: ImprovementIteration;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { changes, isLoading, error } = useAttemptChanges(
    session.agent_id,
    session.id,
    round.number,
  );
  const { evidence } = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const sources = Object.fromEntries((evidence?.items ?? []).map((item) => [item.run_id, item]));
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("attemptChanges.loading")}</p>;
  const tested = changes.filter(
    (hunk) => !round.included_hunk_ids || round.included_hunk_ids.includes(hunk.id),
  );
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium">{t("acceptChanges", { count: tested.length })}</h3>
      {tested.map((hunk) => (
        <MeasuredChange key={hunk.id} hunk={hunk} sources={sources} />
      ))}
    </section>
  );
}
