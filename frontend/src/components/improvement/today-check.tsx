"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useEvalRun, useEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalRunEstimate, EvalRunRequest } from "@/types/eval-runs";

/** Asks the published version the test questions once, with nothing compared beside it. */
function request(datasetId: string): EvalRunRequest {
  return {
    dataset_id: datasetId,
    candidate: "version",
    model_profile_ids: [],
    paired_baseline: false,
    from_recordings: false,
    live_reads: false,
  };
}

/** Today's answers to the test questions, priced and run without leaving the wizard. */
export function TodayCheck({ agentId, datasetId }: { agentId: string; datasetId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const runs = useEvalRuns(agentId);
  const [quote, setQuote] = useState<{ datasetId: string; value: EvalRunEstimate } | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const priceRun = runs.estimate.mutateAsync;
  useEffect(() => {
    let current = true;
    priceRun(request(datasetId)).then(
      (value) => {
        if (current) setQuote({ datasetId, value });
      },
      (failure: unknown) => {
        if (current) setError(getErrorMessage(failure, tErrors));
      },
    );
    return () => {
      current = false;
    };
  }, [datasetId, priceRun, tErrors]);
  if (runId) return <TodayResult runId={runId} />;
  const priced = quote?.datasetId === datasetId ? quote.value : null;
  return (
    <section className="space-y-3 rounded-lg border p-4" data-tour="improvement-today-check">
      <p className="text-sm">{t("todayCheckBody")}</p>
      {priced && (
        <p className="text-sm">
          {t("todayCheckQuote", { count: priced.cases, cost: usd(priced.total_usd, locale) })}
        </p>
      )}
      <Button
        variant="outline"
        disabled={!priced?.affordable || runs.start.isPending}
        onClick={() =>
          void (async () => {
            setError(null);
            try {
              setRunId((await runs.start.mutateAsync(request(datasetId))).id);
            } catch (failure) {
              setError(getErrorMessage(failure, tErrors));
            }
          })()
        }
      >
        {t("baseline")}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}

function TodayResult({ runId }: { runId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { run, error } = useEvalRun(runId);
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (!run || run.status === "queued" || run.status === "running")
    return <p role="status">{t("todayChecking")}</p>;
  const arm = run.arms.find((item) => item.role === "candidate");
  if (run.status !== "completed" || !arm) return <p role="alert">{t("baselineUnavailable")}</p>;
  return (
    <p role="status" className="text-sm font-medium">
      {t("todayHandled", { passed: arm.summary.passed, total: arm.summary.cases })}
    </p>
  );
}
