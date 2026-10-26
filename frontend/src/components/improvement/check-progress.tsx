"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useEvalRun } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import type { EvalRun } from "@/types/eval-runs";
import type { Improvement } from "@/types/improvement";

type Stage = "asking" | "grading" | "repeating";
type StageState = "done" | "running" | "pending";

function stages(run: EvalRun, judging: boolean): Record<Stage, StageState> {
  const finished = run.status === "completed";
  const asked = finished || run.first_done >= run.first_total;
  const repeating = run.attempts_total > run.first_total;
  return {
    asking: asked ? "done" : "running",
    grading: finished ? "done" : judging || asked ? "running" : "pending",
    repeating: finished ? "done" : repeating && asked ? "running" : "pending",
  };
}

/** What the test of the changes is doing now, without the result it has not reached. */
export function CheckProgress({
  session,
  onShowResult,
}: {
  session: Improvement;
  onShowResult: () => void;
}) {
  const t = useTranslations("improvement");
  const round = session.iterations.find((item) => item.number === session.iteration);
  const runId = round?.eval_run_ids.at(-1);
  const active = ["queued", "running"].includes(session.status);
  const measured = session.iterations.some((item) => item.verdict !== null);
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6" data-tour="improvement-check">
      <h2 className="font-medium">{t("checkTitle")}</h2>
      {session.stop_reason === "budget" && (
        <p role="alert" className="text-warning text-sm">
          {t("checkNotStarted")}
        </p>
      )}
      {active &&
        (runId ? (
          <RunStages runId={runId} judging={session.stage === "judging"} />
        ) : (
          <p className="text-sm">{t("checkPreparing")}</p>
        ))}
      {active && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("background")}
        </p>
      )}
      {!active && measured && (
        <div className="space-y-3">
          <p className="text-sm">{t("checkFinished")}</p>
          <Button onClick={onShowResult}>{t("showResult")}</Button>
        </div>
      )}
      {!active && !measured && session.stop_reason !== "budget" && (
        <p className="text-muted-foreground text-sm">{t("checkSkipped")}</p>
      )}
    </section>
  );
}

function RunStages({ runId, judging }: { runId: string; judging: boolean }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const { run, error } = useEvalRun(runId);
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (!run) return <p role="status">{t("loading")}</p>;
  const state = stages(run, judging);
  return (
    <>
      <p className="text-sm">{t("checkQuestions", { count: run.cases })}</p>
      <ol className="space-y-2 text-sm">
        {(["asking", "grading", "repeating"] as const).map((stage) => (
          <li key={stage} className="flex items-start gap-2">
            <span className="text-muted-foreground w-24 shrink-0">
              {t(`stepState.${state[stage]}`)}
            </span>
            <span className={state[stage] === "running" ? "font-medium" : undefined}>
              {t(`checkStage.${stage}`, { count: run.attempts_total - run.first_total })}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
