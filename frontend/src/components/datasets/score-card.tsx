"use client";

import { useState } from "react";
import Link from "next/link";
import { ExternalLink, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import type { NoteTarget } from "@/hooks/use-scoring";
import { ROUTES } from "@/lib/constants";
import { reasonKey, reasonKeyOf } from "@/lib/scoring";
import { formatDateTime } from "@/lib/utils";
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
  /** Score the same answer again. Absent for somebody who may not run the dataset. */
  onRescore?: () => void;
  /** Make the reviewer's note a judge criterion. Absent for somebody who may not edit. */
  onNoteToCriterion?: (target: NoteTarget) => void;
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
        {result.rule && (
          <p className="text-muted-foreground mt-1 text-xs">{t("rule", { rule: result.rule })}</p>
        )}
        {result.judge_said && (
          <p className="text-muted-foreground mt-1 max-h-40 overflow-y-auto font-mono text-xs break-words whitespace-pre-wrap">
            {t("judgeSaid", { said: result.judge_said })}
          </p>
        )}
        {result.unverified && (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{t("unverifiedGrade")}</p>
        )}
        {result.unverified_quotes.length > 0 && (
          <p className="text-muted-foreground/80 mt-1 text-xs italic">
            {t("unverified", { quotes: result.unverified_quotes.join(" · ") })}
          </p>
        )}
      </div>
      {result.judge_run_id !== null &&
        (result.status === "error" ? (
          <Link
            href={`${ROUTES.RUNS}?run=${result.judge_run_id}`}
            className="shrink-0 text-xs underline"
          >
            {t("openJudgeRun")}
          </Link>
        ) : (
          <Link
            href={`${ROUTES.RUNS}?run=${result.judge_run_id}`}
            className="text-muted-foreground hover:text-foreground shrink-0"
            aria-label={t("judgeRun")}
            title={t("judgeRun")}
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </Link>
        ))}
    </li>
  );
}

/** Which agent answered, at which version, on which model, and when it was graded. */
function ScoreSource({ score }: { score: CaseScore }) {
  const t = useTranslations("datasets.scoring");
  const locale = useLocale();
  return (
    <span className="text-muted-foreground ml-auto flex flex-wrap items-center gap-2 text-xs">
      {score.agent_name !== null && (
        <span className="text-foreground font-medium">
          {score.agent_version === null
            ? t("agentDraft", { name: score.agent_name })
            : t("agentVersion", { name: score.agent_name, version: score.agent_version })}
        </span>
      )}
      {score.run_model !== null && <span className="font-mono">{score.run_model}</span>}
      <time dateTime={score.created_at}>{formatDateTime(score.created_at, locale)}</time>
      {score.eval_run_id !== null && score.agent_id !== null ? (
        <Link
          href={`${ROUTES.AGENTS}/${score.agent_id}/evals/${score.eval_run_id}`}
          className="underline"
        >
          {t("evalRunLink")}
        </Link>
      ) : (
        score.run_id !== null && (
          <Link href={`${ROUTES.RUNS}?run=${score.run_id}`} className="underline">
            {t("scoredRun")}
          </Link>
        )
      )}
    </span>
  );
}

/** What each scorer found: the ones that did not pass first, the passing ones folded. */
function Results({ results }: { results: ScorerResult[] }) {
  const t = useTranslations("datasets.scoring");
  const [open, setOpen] = useState(false);
  const held = results.filter((result) => result.status !== "pass");
  const passed = results.filter((result) => result.status === "pass");
  const shown = open || held.length === 0 ? [...held, ...passed] : held;
  return (
    <div>
      <ul className="divide-y">
        {shown.map((result, index) => (
          <ResultRow key={`${result.scorer}:${result.name}:${index}`} result={result} />
        ))}
      </ul>
      {held.length > 0 && passed.length > 0 && (
        <Button
          variant="link"
          size="sm"
          className="h-auto px-0"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? t("hidePassed") : t("showPassed", { count: passed.length })}
        </Button>
      )}
    </div>
  );
}

/** Why nobody reached a verdict on the answer, and the way to ask again. */
function NotGraded({
  code,
  onRescore,
  busy,
}: {
  code: string;
  onRescore?: () => void;
  busy: boolean;
}) {
  const t = useTranslations("datasets.scoring");
  const known = reasonKeyOf(code);
  return (
    <div className="bg-muted/40 flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-sm">
      <p className="min-w-0 flex-1">
        {known ? t(known) : t("notGradedCode", { code })}
        {onRescore && ` ${t("notGradedWhy")}`}
      </p>
      {onRescore && (
        <Button size="sm" variant="outline" disabled={busy} onClick={onRescore}>
          {t("rescore")}
        </Button>
      )}
    </div>
  );
}

/**
 * One answer graded against one case: what the case asked and expected, what the
 * agent answered, what each scorer found and why, and a person's review decision.
 *
 * The decision settles the outcome but is shown apart from the scorers, never in
 * place of them - the judge's opinion stays readable after it is overruled.
 */
export function ScoreCard({
  score,
  onVerdict,
  onReview,
  onRescore,
  onNoteToCriterion,
  busy = false,
}: ScoreCardProps) {
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

      {score.judge_model !== null && score.judge_model === score.run_model && (
        <p className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("judgeSameModel", { model: score.judge_model })}
        </p>
      )}
      <ScoreExpectation score={score} />
      <ScoreAnswer answer={score.answer} hidden={score.answer_hidden} />

      {score.passed === null && score.unscored_reason !== null && (
        <NotGraded code={score.unscored_reason} onRescore={onRescore} busy={busy} />
      )}
      <Results results={score.results} />

      {(onVerdict || sendable || (decided && score.human_note)) && (
        <ScoreDecision
          decided={score.human_passed}
          note={score.human_note}
          onVerdict={onVerdict}
          onReview={sendable ? onReview : undefined}
          onNoteToCriterion={decided ? onNoteToCriterion : undefined}
          busy={busy}
        />
      )}
    </article>
  );
}
