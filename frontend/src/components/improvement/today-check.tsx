"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usd } from "@/components/evals/format";
import {
  EnableAiAssistanceLink,
  GRADING_MODEL_ANCHOR,
} from "@/components/teams/enable-ai-assistance-link";
import { Button, Checkbox } from "@/components/ui";
import { useDraftEvalRuns, useEvalRun, useEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import type { EvalRun, EvalRunEstimate, EvalRunRequest, EvalStability } from "@/types/eval-runs";

/** Below this many questions each is asked twice unless switched off; at it and above, once. */
const TWICE_BELOW = 40;
/** How many of the draft's latest runs are looked through for this dataset's. */
const KEPT_RUNS = 20;

/**
 * Asks the draft the test questions with nothing compared beside it - each twice
 * for a stability run, which says how steady the answers and their grading are.
 */
function request(datasetId: string, twice: boolean): EvalRunRequest {
  return {
    dataset_id: datasetId,
    candidate: "draft",
    model_profile_ids: [],
    paired_baseline: false,
    from_recordings: false,
    live_reads: false,
    ...(twice ? { stability: true } : {}),
  };
}

/** The newest test of the draft as it stands on this dataset that compared nothing, a stability one first. */
function keptRun(runs: EvalRun[], datasetId: string): EvalRun | undefined {
  const mine = runs.filter(
    (run) => run.dataset_id === datasetId && run.arms.every((arm) => arm.role === "candidate"),
  );
  return mine.find((run) => run.purpose === "stability") ?? mine[0];
}

/**
 * Today's answers to the test questions, priced and run without leaving the
 * wizard. A test already made of the draft as it stands is shown again after a
 * refresh, rather than asked for twice.
 */
export function TodayCheck({ agentId, datasetId }: { agentId: string; datasetId: string }) {
  const t = useTranslations("improvement");
  const kept = useDraftEvalRuns(agentId, { limit: KEPT_RUNS });
  const [started, setStarted] = useState<{ datasetId: string; id: string } | null>(null);
  const [again, setAgain] = useState(false);
  if (kept.isLoading) return <p role="status">{t("todayLoading")}</p>;
  const shown =
    started?.datasetId === datasetId
      ? started.id
      : again
        ? undefined
        : keptRun(kept.runs, datasetId)?.id;
  if (shown) {
    return (
      <TodayResult
        runId={shown}
        datasetId={datasetId}
        onAgain={() => {
          setStarted(null);
          setAgain(true);
        }}
      />
    );
  }
  return (
    <TodayStart
      agentId={agentId}
      datasetId={datasetId}
      onStarted={(id) => setStarted({ datasetId, id })}
    />
  );
}

function TodayStart({
  agentId,
  datasetId,
  onStarted,
}: {
  agentId: string;
  datasetId: string;
  onStarted: (runId: string) => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const runs = useEvalRuns(agentId);
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [quote, setQuote] = useState<{
    datasetId: string;
    twice: boolean;
    value: EvalRunEstimate;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const size = quote?.datasetId === datasetId ? quote.value.cases : null;
  const twice = chosen ?? (size === null || size < TWICE_BELOW);
  const priceRun = runs.estimate.mutateAsync;
  useEffect(() => {
    let current = true;
    priceRun(request(datasetId, twice)).then(
      (value) => {
        if (current) setQuote({ datasetId, twice, value });
      },
      (failure: unknown) => {
        if (current) setError(getErrorMessage(failure, tErrors));
      },
    );
    return () => {
      current = false;
    };
  }, [datasetId, twice, priceRun, tErrors]);
  const priced = quote?.datasetId === datasetId && quote.twice === twice ? quote.value : null;
  // A stability run asks every question again, so its ceiling is spent, not a maximum.
  const cost = (estimate: EvalRunEstimate) =>
    twice
      ? String(Number(estimate.total_usd) + Number(estimate.rerun_ceiling_usd))
      : estimate.total_usd;
  return (
    <section className="space-y-3 rounded-lg border p-4" data-tour="improvement-today-check">
      <p className="text-sm">{t("todayCheckBody")}</p>
      <label className="flex items-start gap-2 text-sm">
        <Checkbox
          className="mt-0.5"
          checked={twice}
          onCheckedChange={(checked) => setChosen(checked === true)}
        />
        <span>
          {t("todayTwice")}
          <span className="text-muted-foreground block text-xs">{t("todayTwiceHint")}</span>
        </span>
      </label>
      {priced && (
        <p className="text-sm">
          {t("todayCheckQuote", { count: priced.cases, cost: usd(cost(priced), locale) })}
        </p>
      )}
      <Button
        variant="outline"
        disabled={!priced?.affordable || runs.start.isPending}
        onClick={() =>
          void (async () => {
            setError(null);
            try {
              onStarted((await runs.start.mutateAsync(request(datasetId, twice))).id);
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

function TodayResult({
  runId,
  datasetId,
  onAgain,
}: {
  runId: string;
  datasetId: string;
  onAgain: () => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { run, error } = useEvalRun(runId);
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (!run || run.status === "queued" || run.status === "running")
    return <p role="status">{t("todayChecking")}</p>;
  const arm = run.arms.find((item) => item.role === "candidate");
  return (
    <div className="space-y-3">
      {run.status !== "completed" || !arm ? (
        <p role="alert">{t("baselineUnavailable")}</p>
      ) : (
        <>
          <p role="status" className="text-sm font-medium">
            {t("todayBreakdown", {
              total: arm.summary.cases,
              passed: arm.summary.passed,
              failing: arm.summary.cases - arm.summary.passed,
              asked: run.stability ? "yes" : "no",
              unstable: run.stability?.unstable ?? 0,
            })}
          </p>
          {run.stability && <Stability stability={run.stability} datasetId={datasetId} />}
        </>
      )}
      <Button variant="outline" size="sm" onClick={onAgain}>
        {t("todayAgain")}
      </Button>
    </div>
  );
}

/** How many questions were graded differently when asked again, and what to fix when too many were. */
function Stability({ stability, datasetId }: { stability: EvalStability; datasetId: string }) {
  const t = useTranslations("improvement");
  const orgId = useOrgStore((state) => state.activeOrgId);
  return (
    <>
      {stability.noisy && (
        <div
          role="alert"
          className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm"
        >
          <p className="flex items-start gap-2 font-medium">
            <TriangleAlert
              className="mt-0.5 h-4 w-4 shrink-0 text-amber-700 dark:text-amber-400"
              aria-hidden
            />
            {t("todayNoisy")}
          </p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>
              <Link
                className="underline underline-offset-4"
                href={`${ROUTES.DATASET_DETAIL(datasetId)}?tab=grading`}
              >
                {t("todayNoisyCriteria")}
              </Link>
              <span className="text-muted-foreground block text-xs">
                {t("todayNoisyCriteriaHint")}
              </span>
            </li>
            {orgId && (
              <li>
                <EnableAiAssistanceLink orgId={orgId} anchor={GRADING_MODEL_ANCHOR}>
                  {t("todayNoisyModel")}
                </EnableAiAssistanceLink>
              </li>
            )}
          </ul>
        </div>
      )}
    </>
  );
}
