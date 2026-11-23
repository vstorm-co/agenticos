"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";

import { useTranslations } from "next-intl";
import { useAttemptChanges, useImprovementEvidence } from "@/hooks/use-improvements";
import { subjectOf } from "@/lib/improvement-subject";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { MeasuredChange, measuredHunk } from "./measured-change";
import { MarkdownContent } from "@/components/chat/markdown-content";
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
          <NativeDisclosure key={round.id} open={index === 0} className="space-y-3">
            <summary className="bg-card cursor-pointer rounded-xl border px-4 py-3 text-sm font-medium">
              {heldBack
                ? t("heldBack")
                : t("triedAttempt", {
                    number: round.number,
                    verdict: round.verdict ?? (round.batch_id ? "unmeasured" : "none"),
                    dropped: round.dropped.length,
                  })}
            </summary>
            {round.batch_id && !heldBack && <AttemptProposals session={session} round={round} />}
          </NativeDisclosure>
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
    subjectOf(session),
    session.id,
    round.number,
  );
  const { evidence } = useImprovementEvidence(subjectOf(session), { sessionId: session.id });
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
  report = false,
}: {
  session: Improvement;
  round: ImprovementIteration;
  report?: boolean;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { changes, isLoading, error } = useAttemptChanges(
    subjectOf(session),
    session.id,
    round.number,
  );
  const { evidence } = useImprovementEvidence(subjectOf(session), { sessionId: session.id });
  const sources = Object.fromEntries((evidence?.items ?? []).map((item) => [item.run_id, item]));
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("attemptChanges.loading")}</p>;
  const tested = changes.filter(
    (hunk) => !round.included_hunk_ids || round.included_hunk_ids.includes(hunk.id),
  );
  return (
    <section className="space-y-3">
      {!report && (
        <h3 className="text-sm font-medium">{t("acceptChanges", { count: tested.length })}</h3>
      )}
      {tested.map((hunk, index) =>
        report ? (
          <article key={hunk.id} className="space-y-3 border-b pb-5 last:border-0 last:pb-0">
            {tested.length > 1 && (
              <h3 className="text-sm font-medium">
                {t("workspace.change", { number: index + 1 })}
              </h3>
            )}
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{hunk.rationale}</p>
            {["instructions", "skill_body", "skill_description"].includes(hunk.kind) &&
              hunk.new_text && (
                <div className="bg-muted/40 rounded-lg p-4 text-sm leading-relaxed wrap-anywhere">
                  <MarkdownContent content={measuredHunk(hunk).new_text} inertImages />
                </div>
              )}
            <NativeDisclosure className="text-sm">
              <summary className="text-muted-foreground cursor-pointer">
                {t("workspace.exactChange")}
              </summary>
              <div className="mt-3">
                <MeasuredChange hunk={hunk} sources={sources} />
              </div>
            </NativeDisclosure>
          </article>
        ) : (
          <MeasuredChange key={hunk.id} hunk={hunk} sources={sources} />
        ),
      )}
      {report && tested.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("attemptChanges.none")}</p>
      )}
    </section>
  );
}
