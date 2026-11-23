"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, ListCard } from "@/components/ui";
import { isClosed } from "@/lib/improvement-steps";
import { usd } from "@/components/evals/format";
import type { Improvement } from "@/types/improvement";
import { AttemptChoice } from "./attempt-choice";
import { GAINS, criteriaSentences } from "./criteria";
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
  evidence,
  changes,
}: {
  evidence?: ReactNode;
  changes?: ReactNode;
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
      <Card className="min-w-0 space-y-5 p-4 sm:p-5">
        <ResultDecision
          session={session}
          agent={agent}
          candidate={candidate}
          topics={topics.length}
          canAccept={canAccept}
          onAccept={onAccept}
          onStarted={onStarted}
        />
        <div className="border-t pt-4">
          <ResultSummary session={session} round={chosen} />
        </div>
      </Card>
      {(changes || evidence) && (
        <div className="min-w-0 space-y-4">
          {changes && (
            <ListCard
              role="region"
              aria-label={t("workspace.changes")}
              title={t("workspace.changes")}
            >
              {changes}
            </ListCard>
          )}
          {evidence && (
            <ListCard
              role="region"
              aria-label={t("workspace.evidence")}
              title={t("workspace.evidence")}
            >
              {evidence}
            </ListCard>
          )}
        </div>
      )}
      {!isClosed(session) && <ResultAttempts session={session} knowledgeCheck={knowledgeCheck} />}
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

export function ResultAttempts({
  session,
  knowledgeCheck,
  openFirst = false,
}: {
  openFirst?: boolean;
  session: Improvement;
  knowledgeCheck: ReactNode;
}) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const host =
    session.iterations.find((round) => round.id === session.best_iteration_id) ??
    session.iterations.at(-1);
  return (
    <div className="space-y-4">
      {session.iterations.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3 className="text-sm font-medium">{t("attemptsTitle")}</h3>
            <p className="text-muted-foreground text-xs">
              {t("sessionTotal", { total: usd(session.spent_usd, locale) })}
            </p>
          </div>
          {session.iterations.map((round, index) => (
            <AttemptRow
              key={round.id}
              session={session}
              round={round}
              initiallyOpen={openFirst && index === 0}
              extra={round.id === host?.id ? knowledgeCheck : undefined}
            />
          ))}
        </section>
      )}
    </div>
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
function headline(
  t: Translate,
  locale: string,
  session: Improvement,
  agent: string,
  topics: number,
): string[] {
  const rounds = session.iterations.filter(
    (round) => round.verdict !== null && round.number <= session.max_iterations,
  );
  const chosen = session.iterations.find((round) => round.id === session.best_iteration_id);
  const decided = session.status === "accepted" || session.status === "published";
  const sentences: string[] = [];
  const better = (round: (typeof rounds)[number]) => {
    const criteria = criteriaSentences(t, locale, round, agent);
    if (round.verdict === "better")
      return [
        t("resultDecision.better", {
          number: round.number,
          agent,
          fixed: Number(round.verdict_detail?.fixed ?? 0),
        }),
        ...criteria,
      ];
    return criteria.length
      ? criteria
      : [t("resultDecision.criteriaBetter", { number: round.number, agent })];
  };
  const gained = chosen !== undefined && GAINS.includes(chosen.verdict);
  if (session.status === "ready" && chosen) {
    sentences.push(
      ...(gained ? better(chosen) : [t("resultDecision.chosen", { number: chosen.number })]),
    );
  } else if (session.status === "failed") {
    sentences.push(t("resultDecision.failed"));
  } else if (decided && chosen && gained) {
    sentences.push(...better(chosen));
  } else {
    sentences.push(t("resultDecision.noneBetter", { count: rounds.length, agent }));
    for (const round of rounds) {
      if (round.verdict === "regression")
        sentences.push(
          t("resultDecision.worse", {
            number: round.number,
            broken: Number(round.verdict_detail?.broken ?? 0),
          }),
        );
      else if (round.verdict === "criteria_worse")
        sentences.push(...criteriaSentences(t, locale, round, agent));
    }
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
  const told = ["max_iterations", "no_change", "regression", "criteria_worse"];
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
    (round) => GAINS.includes(round.verdict) && round.number <= session.max_iterations,
  );
  const diagnosed = noisy && !better;
  const closed = isClosed(session);
  const Summary = closed ? "h2" : "p";
  const topicsButton = (variant: "default" | "outline") => (
    <Button asChild variant={variant}>
      <a href={`#${DOCUMENTS_ANCHOR}`}>{t("resultDecision.reviewTopics")}</a>
    </Button>
  );
  return (
    <section className="min-w-0 space-y-3" data-tour="improvement-decision">
      {!closed && <h2 className="text-lg font-medium">{t("resultDecision.title")}</h2>}
      <Summary
        role={session.status === "failed" && session.stop_reason ? "alert" : undefined}
        className={closed ? "text-base leading-relaxed font-medium" : "text-sm"}
      >
        {[
          ...(diagnosed && noise ? [noiseSentence(t, locale, noise, agent)] : []),
          ...headline(t, locale, session, agent, topics),
        ].join(" ")}
      </Summary>
      {session.status === "published" && session.published_version != null && (
        <Link
          className="inline-block text-sm underline underline-offset-4"
          href={`/agents/${session.agent_id}?tab=history&from=${session.published_version}&to=${session.published_version}`}
        >
          {t("decision.openVersion", { version: session.published_version })}
        </Link>
      )}
      {noise && <TooFewShared noise={noise} />}
      {noisy && better && noise && (
        <p className="text-muted-foreground text-sm">
          {noiseSentence(t, locale, noise, agent, { note: true })}
        </p>
      )}
      <AttemptChoice session={session} agent={agent} />
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
