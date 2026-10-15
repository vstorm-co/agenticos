"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { reasonKey } from "@/lib/scoring";
import type { CaseScore, ScorerResult } from "@/types/scoring";
import { ScoreAnswer } from "./score-answer";
import { ScoreDecision, type Verdict } from "./score-decision";
import { ScoreExpectation } from "./score-expectation";

export type { Verdict } from "./score-decision";

interface ScoreCardProps {
  score: CaseScore;
  /** Record a person's review decision. Absent for somebody who may not decide. */
  onVerdict?: (verdict: Verdict) => void;
  /** Put the score in the review queue. Absent when it cannot be sent. */
  onReview?: () => void;
  busy?: boolean;
}

const STATUS_VARIANT = {
  pass: "default",
  fail: "destructive",
  skipped: "secondary",
  error: "outline",
} as const;

function OutcomeBadge({ outcome }: { outcome: boolean | null }) {
  const t = useTranslations("datasets.scoring");
  if (outcome === null) return <Badge variant="secondary">{t("unscored")}</Badge>;
  return outcome ? (
    <Badge>{t("passed")}</Badge>
  ) : (
    <Badge variant="destructive">{t("failed")}</Badge>
  );
}

function ResultRow({ result }: { result: ScorerResult }) {
  const t = useTranslations("datasets.scoring");
  const known = reasonKey(result);
  return (
    <li className="flex flex-wrap items-start gap-2 py-2 text-sm">
      <Badge variant={STATUS_VARIANT[result.status]} className="shrink-0 font-normal">
        {t(`status.${result.status}`)}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {t(`scorer.${result.scorer}`)} · <span className="font-mono text-xs">{result.name}</span>
          {!result.required && (
            <span className="text-muted-foreground ml-2 text-xs">{t("optional")}</span>
          )}
        </p>
        <p className="text-muted-foreground break-words">{known ? t(known) : result.reason}</p>
        {result.unverified_quotes.length > 0 && (
          <p className="text-muted-foreground/80 mt-1 text-xs italic">
            {t("unverified", { quotes: result.unverified_quotes.join(" · ") })}
          </p>
        )}
      </div>
      {result.judge_run_id !== null && (
        <Link
          href={`${ROUTES.RUNS}?run=${result.judge_run_id}`}
          className="text-muted-foreground shrink-0 text-xs underline"
        >
          {t("judgeRun")}
        </Link>
      )}
    </li>
  );
}

/** Which agent answered, at which version, on which model, and when it was graded. */
function ScoreSource({ score }: { score: CaseScore }) {
  const t = useTranslations("datasets.scoring");
  const format = useFormatter();
  return (
    <span className="text-muted-foreground ml-auto flex flex-wrap items-center gap-2 text-xs">
      {score.agent_name !== null && (
        <span className="text-foreground font-medium">
          {score.agent_version === null
            ? score.agent_name
            : t("agentVersion", { name: score.agent_name, version: score.agent_version })}
        </span>
      )}
      {score.run_model !== null && <span className="font-mono">{score.run_model}</span>}
      <time dateTime={score.created_at}>
        {format.dateTime(new Date(score.created_at), { dateStyle: "medium", timeStyle: "short" })}
      </time>
      {score.run_id !== null && (
        <Link href={`${ROUTES.RUNS}?run=${score.run_id}`} className="underline">
          {t("scoredRun")}
        </Link>
      )}
    </span>
  );
}

/**
 * One answer graded against one case: what the case asked and expected, what the
 * agent answered, what each scorer found and why, and a person's review decision.
 *
 * The decision settles the outcome but is shown apart from the scorers, never in
 * place of them - the judge's opinion stays readable after it is overruled.
 */
export function ScoreCard({ score, onVerdict, onReview, busy = false }: ScoreCardProps) {
  const t = useTranslations("datasets.scoring");
  const sendable = onReview !== undefined && score.review_state === "none";
  const decided = score.human_passed !== null;

  return (
    <article className="space-y-3 rounded-lg border p-4">
      <header className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={score.outcome} />
        {decided && <span className="text-muted-foreground text-xs">{t("decidedByPerson")}</span>}
        {score.review_state === "pending" && <Badge variant="outline">{t("awaitingReview")}</Badge>}
        <ScoreSource score={score} />
      </header>

      <ScoreExpectation score={score} />
      <ScoreAnswer answer={score.answer} />

      <ul className="divide-y">
        {score.results.map((result, index) => (
          <ResultRow key={`${result.scorer}:${result.name}:${index}`} result={result} />
        ))}
      </ul>

      {(onVerdict || sendable || (decided && score.human_note)) && (
        <ScoreDecision
          decided={score.human_passed}
          note={score.human_note}
          onVerdict={onVerdict}
          onReview={sendable ? onReview : undefined}
          busy={busy}
        />
      )}
    </article>
  );
}
