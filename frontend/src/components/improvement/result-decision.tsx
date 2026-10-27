"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import type { Improvement } from "@/types/improvement";
import { ContinueSession, continuation } from "./continue-session";
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
      {!host && <Details summary={t("showDetails")}>{knowledgeCheck}</Details>}
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

const active = (session: Improvement) => ["queued", "running"].includes(session.status);

/** The verdicts, the knowledge gaps and why the session stopped, as plain sentences. */
function headline(t: Translate, session: Improvement, agent: string, topics: number): string[] {
  const rounds = session.iterations.filter(
    (round) => round.verdict !== null && round.number <= session.max_iterations,
  );
  const chosen = session.iterations.find((round) => round.id === session.best_iteration_id);
  const sentences: string[] = [];
  if (session.status === "ready" && chosen) {
    sentences.push(
      chosen.verdict === "better"
        ? t("resultDecision.better", {
            number: chosen.number,
            agent,
            fixed: Number(chosen.verdict_detail?.fixed ?? 0),
          })
        : t("resultDecision.chosen", { number: chosen.number }),
    );
  } else if (session.status === "failed") {
    sentences.push(t("resultDecision.failed"));
  } else if (active(session)) {
    sentences.push(t("resultDecision.working"));
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
  if (topics > 0) sentences.push(t("resultDecision.topics", { count: topics }));
  const missingHeldOut = Number(session.iterations[0]?.verdict_detail?.missing_holdout ?? 0);
  if (session.status !== "ready" && session.stop_reason)
    sentences.push(
      session.stop_reason === "max_iterations"
        ? t("resultDecision.limit", { max: session.max_iterations })
        : session.stop_reason === "no_data" && missingHeldOut > 0
          ? t("tooFewHeldOut", { needed: missingHeldOut })
          : t(`stop.${session.stop_reason}`),
    );
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
  const readOnly = useReadOnly();
  const situation = resultSituation(session, { candidate, topics });
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
        {headline(t, session, agent, topics).join(" ")}
      </p>
      {!readOnly && !active(session) && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t("resultDecision.options")}</h3>
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
    </section>
  );
}
