"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { reasonKeyOf } from "@/lib/scoring";
import type { DatasetCaseContent } from "@/types/datasets";
import type { CallOutcome, EvalAttempt, EvalRunArm } from "@/types/eval-runs";
import { seconds, usd } from "./format";
import { sideName } from "./names";

const CALL_TONE: Record<CallOutcome, "secondary" | "warning" | "outline"> = {
  executed: "secondary",
  replayed: "outline",
  blocked: "warning",
  divergent: "warning",
};

function Attempt({ attempt }: { attempt: EvalAttempt }) {
  const t = useTranslations("evals.case");
  const tScoring = useTranslations("datasets.scoring");
  const locale = useLocale();
  // An answer no scorer reached a verdict on is not graded, not merely undecided.
  const why = attempt.outcome === null ? (attempt.score?.unscored_reason ?? null) : null;
  const known = reasonKeyOf(why);
  return (
    <div className="space-y-2 rounded-md border p-3">
      <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
        <span>{attempt.attempt === 0 ? t("firstAnswer") : t("rerun", { n: attempt.attempt })}</span>
        <span>
          {why === null
            ? t(`outcome.${String(attempt.outcome)}`)
            : t("notGraded", { reason: known ? tScoring(known) : why })}
        </span>
        <span>{usd(attempt.cost_usd, locale)}</span>
        <span>{seconds(attempt.latency_ms, locale)}</span>
      </p>
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
        <ul className="space-y-0.5 text-xs">
          {attempt.score.results.map((result, index) => (
            <li key={index}>
              <span className="font-medium">{result.name}</span> · {t(`scorer.${result.status}`)} ·{" "}
              <span className="text-muted-foreground">{result.reason}</span>
              {result.rule && (
                <span className="text-muted-foreground block">
                  {tScoring("rule", { rule: result.rule })}
                </span>
              )}
              {result.unverified && (
                <span className="text-warning block">{tScoring("unverifiedGrade")}</span>
              )}
            </li>
          ))}
        </ul>
      )}
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
      <p className="text-muted-foreground text-xs font-medium">{t("title")}</p>
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
          <ul className="space-y-0.5 text-xs">
            {expectation.checks.map(({ type, ...parameters }, index) => (
              <li key={index}>
                <code className="break-all">
                  {type} {JSON.stringify(parameters)}
                </code>
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
  return (
    <div className="space-y-3">
      {expectation && (
        <Expectation expectation={expectation} datasetId={datasetId} caseId={caseId} />
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {arms.map((arm) => {
          const own = attempts.filter((attempt) => attempt.arm_id === arm.id);
          return (
            <div key={arm.id} className="space-y-2">
              <p className="text-muted-foreground text-xs font-medium">
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
