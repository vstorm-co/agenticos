"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEvalCases, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { CaseFlip, EvalCase } from "@/types/eval-runs";

/**
 * Changed held-out questions, each marked newly fixed or newly broken. Only a change
 * the repeat answers confirmed counts in the verdict; the rest wait under their own heading.
 */
export function ChangedAnswers({
  runId,
  agentId,
  flips,
  baselineId,
  candidateId,
  attributions,
}: {
  runId: string;
  agentId: string;
  flips: CaseFlip[];
  baselineId: string;
  candidateId: string;
  attributions: Record<string, string>;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { cases, error, isLoading } = useEvalCases(runId, {
    caseIds: flips.slice(0, 100).map((flip) => flip.case_id),
    limit: 50,
  });
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("loading")}</p>;
  const byCase = new Map(flips.map((flip) => [flip.case_id, flip]));
  const confirmed = cases.filter((item) => byCase.get(item.case_id)?.confirmed);
  const pending = cases.filter((item) => !byCase.get(item.case_id)?.confirmed);
  const row = (item: EvalCase) => (
    <ChangedRow
      key={item.case_id}
      item={item}
      flip={byCase.get(item.case_id)!.flip}
      baselineId={baselineId}
      candidateId={candidateId}
      attributions={attributions}
    />
  );
  return (
    <div className="space-y-3">
      {confirmed.map(row)}
      {pending.length > 0 && (
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("notConfirmedYet", { count: pending.length })}
          </summary>
          <div className="mt-3 space-y-3">{pending.map(row)}</div>
        </details>
      )}
      <Link className="text-sm underline" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}

function ChangedRow({
  item,
  flip,
  baselineId,
  candidateId,
  attributions,
}: {
  item: EvalCase;
  flip: CaseFlip["flip"];
  baselineId: string;
  candidateId: string;
  attributions: Record<string, string>;
}) {
  const t = useTranslations("improvement");
  const before = item.attempts.find((a) => a.arm_id === baselineId && a.attempt === 0);
  const after = item.attempts.find((a) => a.arm_id === candidateId && a.attempt === 0);
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <p
        className={
          flip === "regression"
            ? "text-destructive text-xs font-medium"
            : "text-success text-xs font-medium"
        }
      >
        {t(flip === "regression" ? "newlyBroken" : "newlyFixed")}
      </p>
      <h4 className="text-sm font-medium">{item.input}</h4>
      <div className="grid gap-4 md:grid-cols-2">
        {[
          { label: t("before"), value: before?.answer },
          { label: t("after"), value: after?.answer },
        ].map((v) => (
          <div key={v.label} className="min-w-0">
            <p className="text-muted-foreground text-xs">{v.label}</p>
            <p className="text-sm break-words whitespace-pre-wrap">
              {v.value ?? t("unavailableAnswer")}
            </p>
          </div>
        ))}
      </div>
      {after?.score?.results.map((grade, index) => (
        <p key={index} className="text-muted-foreground text-sm">
          {t("graderSaid", { reason: grade.reason })}
        </p>
      ))}
      <div className="text-sm">
        <p className="font-medium">{t("whichChange")}</p>
        {Object.keys(attributions).length === 0 ? (
          <p className="text-muted-foreground">{t("notAttributed")}</p>
        ) : (
          Object.values(attributions).map((id, index) => (
            <ChangeCause key={id} caseId={item.case_id} runId={id} number={index + 1} />
          ))
        )}
      </div>
    </article>
  );
}
function ChangeCause({ caseId, runId, number }: { caseId: string; runId: string; number: number }) {
  const t = useTranslations("improvement");
  const { run, error: runError } = useEvalRun(runId);
  const { comparison, error } = useEvalComparison(runId, {
    live: run?.status === "queued" || run?.status === "running",
  });
  const item = comparison?.cases.find((c) => c.case_id === caseId);
  return (
    <p className="text-muted-foreground">
      {t(
        error ||
          runError ||
          comparison?.verdict === "invalid" ||
          (run && !["queued", "running", "completed"].includes(run.status))
          ? "attributionFailed"
          : !comparison
            ? "attributionWorking"
            : item && !item.confirmed && (item.flip === "regression" || item.flip === "fixed")
              ? "attributionUnconfirmed"
              : item?.flip === "regression"
                ? "changeBroke"
                : item?.flip === "fixed"
                  ? "changeFixed"
                  : "changeUnchanged",
        { number },
      )}
    </p>
  );
}
