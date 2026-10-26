"use client";

import Link from "next/link";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { reasonKeyOf } from "@/lib/scoring";
import type { DatasetCaseContent } from "@/types/datasets";
import type { ScorerStatus } from "@/types/scoring";
import type { CallOutcome, EvalAttempt, EvalRunArm } from "@/types/eval-runs";
import { CheckSummary } from "./check-summary";
import { percent, seconds, usd } from "./format";
import { sideName } from "./names";
import { SCORER_TONE, VerdictBadge, VerdictIcon, type VerdictTone } from "./verdict-badge";

const CALL_TONE: Record<CallOutcome, "secondary" | "warning" | "outline"> = {
  executed: "secondary",
  replayed: "outline",
  blocked: "warning",
  divergent: "warning",
};

const SCORER_ORDER: Record<ScorerStatus, number> = { fail: 0, error: 1, skipped: 2, pass: 3 };

function outcomeTone(outcome: boolean | null): VerdictTone {
  if (outcome === null) return "undecided";
  return outcome ? "pass" : "fail";
}

function Attempt({ attempt }: { attempt: EvalAttempt }) {
  const t = useTranslations("evals.case");
  const tScoring = useTranslations("datasets.scoring");
  const locale = useLocale();
  // An answer no scorer reached a verdict on is not graded, not merely undecided.
  const why = attempt.outcome === null ? (attempt.score?.unscored_reason ?? null) : null;
  const known = reasonKeyOf(why);
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="bg-muted/40 flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2">
        <p className="text-sm font-semibold">
          {attempt.attempt === 0 ? t("firstAnswer") : t("rerun", { n: attempt.attempt })}
        </p>
        <VerdictBadge
          tone={why === null ? outcomeTone(attempt.outcome) : "undecided"}
          className={why === null ? undefined : "whitespace-normal"}
        >
          {why === null
            ? t(`outcome.${String(attempt.outcome)}`)
            : t("notGraded", { reason: known ? tScoring(known) : why })}
        </VerdictBadge>
        <span className="text-muted-foreground text-xs tabular-nums">
          {usd(attempt.cost_usd, locale)}
        </span>
        <span className="text-muted-foreground text-xs tabular-nums">
          {seconds(attempt.latency_ms, locale)}
        </span>
      </div>
      <div className="space-y-2 p-3">
        {attempt.answer !== null && (
          <p className="text-foreground text-sm whitespace-pre-wrap">{attempt.answer}</p>
        )}
        {attempt.error && <p className="text-destructive text-xs">{attempt.error}</p>}
        {attempt.calls.length > 0 && (
          <ul className="space-y-1">
            {attempt.calls.map((call, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant={CALL_TONE[call.outcome]}>{t(`call.${call.outcome}`)}</Badge>
                <code className="break-all">
                  {call.tool}({JSON.stringify(call.args)})
                </code>
              </li>
            ))}
          </ul>
        )}
        {attempt.agent_run_id && (
          <Link
            href={`${ROUTES.RUNS}?run=${attempt.agent_run_id}&view=input`}
            className="text-muted-foreground block text-xs underline underline-offset-4"
          >
            {t("whatTheModelSaw")}
          </Link>
        )}
        {attempt.score && (
          <ul className="divide-border divide-y rounded-md border text-sm">
            {[...attempt.score.results]
              .sort((a, b) => SCORER_ORDER[a.status] - SCORER_ORDER[b.status])
              .map((result, index) => {
                const tone = SCORER_TONE[result.status];
                return (
                  <li key={index}>
                    <details className="group">
                      <summary className="hover:bg-muted/40 flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2">
                        <VerdictIcon tone={tone} />
                        <span className="text-foreground min-w-0 flex-1 font-semibold">
                          {result.name}
                        </span>
                        <VerdictBadge tone={tone}>{t(`scorer.${result.status}`)}</VerdictBadge>
                        {result.score !== null && (
                          <span className="text-muted-foreground tabular-nums">
                            {percent(result.score, locale)}
                          </span>
                        )}
                        <ChevronRight
                          className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                          aria-hidden
                        />
                      </summary>
                      <div className="text-muted-foreground space-y-1 px-3 pb-3 text-xs">
                        <p className="whitespace-pre-wrap">{result.reason}</p>
                        {result.rule && <p>{tScoring("rule", { rule: result.rule })}</p>}
                      </div>
                    </details>
                  </li>
                );
              })}
          </ul>
        )}
      </div>
    </div>
  );
}

/** What the case asks for, read before the answers it is measured against. */
function Expectation({
  expectation,
  datasetId,
  caseId,
}: {
  expectation: DatasetCaseContent;
  datasetId: string;
  caseId: string;
}) {
  const t = useTranslations("evals.case.expect");
  const tDatasets = useTranslations("datasets");
  const calls = expectation.expected_tool_calls;
  return (
    <div className="bg-muted/40 space-y-2 rounded-md border p-3 text-sm">
      <p className="text-sm font-semibold">{t("title")}</p>
      {expectation.reference_answer && (
        <p>
          <span className="text-muted-foreground text-xs">{t("reference")} </span>
          <span className="whitespace-pre-wrap">{expectation.reference_answer}</span>
        </p>
      )}
      {expectation.counter_example && (
        <p>
          <span className="text-muted-foreground text-xs">{t("counterExample")} </span>
          <span className="whitespace-pre-wrap">{expectation.counter_example}</span>
        </p>
      )}
      {calls.length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">
            {t("calls", { order: tDatasets(`orderMode.${expectation.order_mode}`) })}
          </p>
          <ul className="space-y-0.5 text-xs">
            {calls.map((call, index) => (
              <li key={index}>
                <code className="break-all">
                  {call.tool}({JSON.stringify(call.args)})
                </code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {expectation.checks.length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">{t("checks")}</p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {expectation.checks.map((check, index) => (
              <li key={index}>
                <CheckSummary check={check} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <Link
        href={`${ROUTES.DATASET_DETAIL(datasetId)}?tab=cases&case=${caseId}`}
        className="text-muted-foreground block text-xs underline underline-offset-4"
      >
        {t("openDataset")}
      </Link>
    </div>
  );
}

/**
 * One case answered by every side of the run, next to each other - the draft
 * beside what is live when both ran here - under what the case expects, with
 * each answer, its calls and what every scorer said.
 */
export function CaseDetail({
  attempts,
  arms,
  expectation,
  datasetId,
  caseId,
}: {
  attempts: EvalAttempt[];
  arms: EvalRunArm[];
  expectation: DatasetCaseContent | null;
  datasetId: string;
  caseId: string;
}) {
  const t = useTranslations("evals");
  const tScoring = useTranslations("datasets.scoring");
  const unverified = attempts.some((attempt) =>
    attempt.score?.results.some((result) => result.unverified),
  );
  return (
    <div className="space-y-3">
      {expectation && (
        <Expectation expectation={expectation} datasetId={datasetId} caseId={caseId} />
      )}
      {unverified && (
        <p className="bg-warning/10 border-warning/35 flex items-start gap-2 rounded-md border p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {tScoring("unverifiedGrade")}
        </p>
      )}
      <div className={arms.length > 1 ? "grid gap-3 md:grid-cols-2" : "space-y-3"}>
        {arms.map((arm) => {
          const own = attempts.filter((attempt) => attempt.arm_id === arm.id);
          return (
            <div key={arm.id} className="space-y-2">
              <p className="text-sm font-semibold">
                {t("sideModel", { name: sideName(arm, t), model: arm.model_label })}
              </p>
              {own.map((attempt) => (
                <Attempt key={attempt.id} attempt={attempt} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
