"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import type { Improvement } from "@/types/improvement";
import { ContinueSession, continuation } from "./continue-session";
import { NoiseActions, TooFewShared, UnstableQuestions, noiseSentence } from "./measurement-noise";
import { draftCheckShown } from "./knowledge-drafts";
import { DOCUMENTS_ANCHOR, KnowledgeDocuments, ResultSummary, useSessionTopics } from "./outcome";
import { useReadOnly } from "./read-only";
import { AttemptRow } from "./round-results";
import { Details } from "./widgets";

/**
 * The Result step: the decision first, then the figures it rests on, the attempts
 * one row each, and the knowledge the session found missing.
 */
export function ResultStep({
  session,
  agent,
  candidate,
  canAccept,
  knowledgeCheck,
  onAccept,
  onStarted,
}: {
  session: Improvement;
  agent: string;
  candidate: boolean;
  canAccept: boolean;
  /** The knowledge draft check, kept in one attempt's details so the result has one. */
  knowledgeCheck: ReactNode;
  onAccept: () => void;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement");
  const { topics } = useSessionTopics(session);
  const chosen = session.iterations.find((round) => round.id === session.best_iteration_id);
  const host = chosen ?? session.iterations.at(-1);
  return (
    <section className="space-y-4" data-tour="improvement-results">
      <ResultDecision
        session={session}
        agent={agent}
        candidate={candidate}
        topics={topics.length}
        canAccept={canAccept}
        onAccept={onAccept}
        onStarted={onStarted}
      />
      <ResultSummary session={session} round={chosen} />
      {session.iterations.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium">{t("attemptsTitle")}</h3>
          {session.iterations.map((round) => (
            <AttemptRow
              key={round.id}
              session={session}
              round={round}
              extra={round.id === host?.id ? knowledgeCheck : undefined}
            />
          ))}
        </section>
      )}
      {!host && draftCheckShown(session, topics) && (
        <Details summary={t("showDetails")}>{knowledgeCheck}</Details>
      )}
      {topics.length > 0 && (
        <div id={DOCUMENTS_ANCHOR} className="scroll-mt-4">
          <KnowledgeDocuments session={session} />
        </div>
      )}
    </section>
  );
}

type ResultSituation = "failed" | "accept" | "again" | "topics" | "nothing";

/** Which decision the result asks for, most pressing first. */
function resultSituation(
  session: Improvement,
  { candidate, topics }: { candidate: boolean; topics: number },
): ResultSituation {
  if (session.status === "failed") return "failed";
  if (candidate) return "accept";
  if (continuation(session).canContinue) return "again";
  return topics > 0 ? "topics" : "nothing";
}

type Translate = ReturnType<typeof useTranslations>;

/** The verdicts, the knowledge gaps and why the session stopped, as plain sentences. */
function headline(t: Translate, session: Improvement, agent: string, topics: number): string[] {
  const rounds = session.iterations.filter(
    (round) => round.verdict !== null && round.number <= session.max_iterations,
  );
  const chosen = session.iterations.find((round) => round.id === session.best_iteration_id);
  const decided = session.status === "accepted" || session.status === "published";
  const sentences: string[] = [];
  const better = (round: (typeof rounds)[number]) =>
    t("resultDecision.better", {
      number: round.number,
      agent,
      fixed: Number(round.verdict_detail?.fixed ?? 0),
    });
  if (session.status === "ready" && chosen) {
    sentences.push(
      chosen.verdict === "better"
        ? better(chosen)
        : t("resultDecision.chosen", { number: chosen.number }),
    );
  } else if (session.status === "failed") {
    sentences.push(t("resultDecision.failed"));
  } else if (decided && chosen?.verdict === "better") {
    sentences.push(better(chosen));
  } else {
    sentences.push(t("resultDecision.noneBetter", { count: rounds.length, agent }));
    for (const round of rounds.filter((item) => item.verdict === "regression"))
      sentences.push(
        t("resultDecision.worse", {
          number: round.number,
          broken: Number(round.verdict_detail?.broken ?? 0),
        }),
      );
  }
  if (decided && chosen)
    sentences.push(
      session.status === "published"
        ? t("resultDecision.published", {
            number: chosen.number,
            version: session.published_version ?? "unknown",
          })
        : t("resultDecision.acceptedDraft", { number: chosen.number }),
    );
  if (topics > 0) sentences.push(t("resultDecision.topics", { count: topics }));
  const missingHeldOut = Number(session.iterations[0]?.verdict_detail?.missing_holdout ?? 0);
  const limit =
    session.stop_reason === "max_iterations" ||
    (!decided && session.iteration >= session.max_iterations);
  // A verdict's own stop reason repeats the sentences above it.
  const told = ["max_iterations", "no_change", "regression"];
  if (session.status !== "ready" && session.stop_reason && !told.includes(session.stop_reason))
    sentences.push(
      session.stop_reason === "no_data" && missingHeldOut > 0
        ? t("tooFewHeldOut", { needed: missingHeldOut })
        : t(`stop.${session.stop_reason}`),
    );
  if (limit) sentences.push(t("resultDecision.limit", { max: session.max_iterations }));
  else if (session.round_hint && !decided)
    sentences.push(t(`resultDecision.hint.${session.round_hint}`));
  return sentences;
}

/**
 * What the session came to and what the person can do about it, before any figure:
 * one primary action per situation, so the decision is never under the attempts.
 */
function ResultDecision({
  session,
  agent,
  candidate,
  topics,
  canAccept,
  onAccept,
  onStarted,
}: {
  session: Improvement;
  agent: string;
  /** A checked candidate is waiting for a person to accept it. */
  candidate: boolean;
  topics: number;
  /** False while the change selection differs from what was measured. */
  canAccept: boolean;
  onAccept: () => void;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const readOnly = useReadOnly();
  const situation = resultSituation(session, { candidate, topics });
  const noise = session.measurement_noise;
  const noisy = noise?.noisy === true;
  const better = session.iterations.some(
    (round) => round.verdict === "better" && round.number <= session.max_iterations,
  );
  const diagnosed = noisy && !better;
  const topicsButton = (variant: "default" | "outline") => (
    <Button asChild variant={variant}>
      <a href={`#${DOCUMENTS_ANCHOR}`}>{t("resultDecision.reviewTopics")}</a>
    </Button>
  );
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6" data-tour="improvement-decision">
      <h2 className="font-medium">{t("resultDecision.title")}</h2>
      <p
        role={session.status === "failed" && session.stop_reason ? "alert" : undefined}
        className="text-sm"
      >
        {[
          ...(diagnosed && noise ? [noiseSentence(t, locale, noise, agent)] : []),
          ...headline(t, session, agent, topics),
        ].join(" ")}
      </p>
      {noise && <TooFewShared noise={noise} />}
      {noisy && better && noise && (
        <p className="text-muted-foreground text-sm">
          {noiseSentence(t, locale, noise, agent, { note: true })}
        </p>
      )}
      {!readOnly && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t("resultDecision.options")}</h3>
          {diagnosed && <NoiseActions session={session} />}
          <ContinueSession
            session={session}
            emphasis={{
              again: situation === "again" || situation === "failed" ? "default" : "outline",
              end:
                situation === "nothing" ? "default" : situation === "topics" ? "outline" : "ghost",
            }}
            lead={
              situation === "accept" ? (
                <Button disabled={!canAccept} onClick={onAccept}>
                  {t("resultDecision.accept")}
                </Button>
              ) : situation === "topics" ? (
                topicsButton("default")
              ) : situation === "again" && topics > 0 ? (
                topicsButton("outline")
              ) : undefined
            }
            trail={
              situation === "nothing" && (
                <Button asChild variant="outline">
                  <Link href={`/agents/${session.agent_id}/improve/new`}>
                    {t("resultDecision.newSession")}
                  </Link>
                </Button>
              )
            }
            onStarted={onStarted}
          />
          {situation === "nothing" && (
            <p className="text-muted-foreground text-sm">
              {t("resultDecision.newSessionHint", { agent })}
            </p>
          )}
        </div>
      )}
      {diagnosed && noise && <UnstableQuestions noise={noise} />}
    </section>
  );
}
