"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEvalCases, useEvalComparison } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";

/** Changed held-out questions, with answers and the grading that explains the change. */
export function ChangedAnswers({
  runId,
  agentId,
  caseIds,
  baselineId,
  candidateId,
  attributions,
}: {
  runId: string;
  agentId: string;
  caseIds: string[];
  baselineId: string;
  candidateId: string;
  attributions: Record<string, string>;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { cases, error, isLoading } = useEvalCases(runId, {
    caseIds: caseIds.slice(0, 100),
    limit: 50,
  });
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("loading")}</p>;
  return (
    <div className="space-y-3">
      {cases.map((item) => {
        const before = item.attempts.find((a) => a.arm_id === baselineId && a.attempt === 0);
        const after = item.attempts.find((a) => a.arm_id === candidateId && a.attempt === 0);
        return (
          <article key={item.case_id} className="space-y-3 rounded-lg border p-4">
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
                {grade.reason}
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
      })}
      <Link className="text-sm underline" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}
function ChangeCause({ caseId, runId, number }: { caseId: string; runId: string; number: number }) {
  const t = useTranslations("improvement");
  const { comparison, error } = useEvalComparison(runId, { live: true });
  const item = comparison?.cases.find((c) => c.case_id === caseId);
  return (
    <p className="text-muted-foreground">
      {t(
        error
          ? "attributionFailed"
          : !comparison
            ? "attributionWorking"
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
