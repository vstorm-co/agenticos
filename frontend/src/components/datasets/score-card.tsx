"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge, Button, Textarea } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { reasonKey } from "@/lib/scoring";
import { cn } from "@/lib/utils";
import type { CaseScore, ScorerResult } from "@/types/scoring";

/** A verdict as the card hands it back: pass, fail, or `null` to withdraw one. */
export type Verdict = { passed: boolean | null; note: string | null };

interface ScoreCardProps {
  score: CaseScore;
  /** Record a person's verdict. Absent for somebody who may not decide. */
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

/**
 * One run's answer scored against one case: each scorer's verdict and why, and a
 * person's verdict beside them.
 *
 * The person's verdict decides the outcome but is shown apart from the scorers,
 * never in place of them - the judge's opinion stays readable after it is overruled.
 */
export function ScoreCard({ score, onVerdict, onReview, busy = false }: ScoreCardProps) {
  const t = useTranslations("datasets.scoring");
  const [note, setNote] = useState(score.human_note ?? "");
  const decide = (passed: boolean | null) =>
    onVerdict?.({ passed, note: passed === null || note.trim() === "" ? null : note });

  return (
    <article className="space-y-3 rounded-lg border p-4">
      <header className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={score.outcome} />
        {score.human_passed !== null && (
          <span className="text-muted-foreground text-xs">{t("decidedByPerson")}</span>
        )}
        {score.review_state === "pending" && <Badge variant="outline">{t("awaitingReview")}</Badge>}
        {score.run_id !== null && (
          <Link
            href={`${ROUTES.RUNS}?run=${score.run_id}`}
            className="text-muted-foreground ml-auto text-xs underline"
          >
            {t("scoredRun")}
          </Link>
        )}
      </header>

      <ul className="divide-y">
        {score.results.map((result, index) => (
          <ResultRow key={`${result.scorer}:${result.name}:${index}`} result={result} />
        ))}
      </ul>

      {score.human_passed !== null && score.human_note && (
        <p className="text-sm">
          <span className="font-medium">{t("verdictNote")}</span> {score.human_note}
        </p>
      )}

      {(onVerdict || onReview) && (
        <footer className={cn("space-y-2 border-t pt-3", busy && "opacity-60")}>
          {onVerdict && (
            <>
              <Textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t("verdictNotePlaceholder")}
                aria-label={t("verdictNote")}
                rows={2}
              />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy} onClick={() => decide(true)}>
                  {t("markPassed")}
                </Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)}>
                  {t("markFailed")}
                </Button>
                {score.human_passed !== null && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide(null)}>
                    {t("withdrawVerdict")}
                  </Button>
                )}
              </div>
            </>
          )}
          {onReview && score.review_state === "none" && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={onReview}>
              {t("sendToReview")}
            </Button>
          )}
        </footer>
      )}
    </article>
  );
}
