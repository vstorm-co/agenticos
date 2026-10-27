"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useEvalRun } from "@/hooks/use-eval-runs";
import type { EvalRun } from "@/types/eval-runs";
import type { CheckAnswers, Improvement } from "@/types/improvement";
import { isActive } from "@/lib/improvement-steps";
import { AttemptHistory } from "./attempt-history";
import { StepError } from "./step-error";
import { StateBadge, Stepper, type StageState } from "./widgets";

type Stage = "asking" | "grading" | "repeating";

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
  const active = isActive(session);
  const checking = session.stage === "evaluating" || session.stage === "judging";
  const measured = session.iterations.some((item) => item.verdict !== null);
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6" data-tour="improvement-check">
      <h2 className="font-medium">{t("checkTitle")}</h2>
      {session.stop_reason === "budget" && (
        <p role="alert" className="text-warning text-sm">
          {t("checkNotStarted")}
        </p>
      )}
      {active && <AttemptHistory session={session} />}
      {active && (
        <p className="text-sm font-medium">
          {t(checking ? "checkingAttempt" : "writingAgain", {
            number: session.iteration,
            max: session.max_iterations,
          })}
        </p>
      )}
      {active && checking && (session.baseline_answers || session.candidate_answers) && (
        <div className="space-y-3">
          {session.baseline_answers && (
            <AnswerBar
              label={t("checkBars.today")}
              answers={session.baseline_answers}
              note={session.baseline_answers.reused ? t("checkBars.reused") : undefined}
            />
          )}
          {session.candidate_answers && (
            <AnswerBar label={t("checkBars.changed")} answers={session.candidate_answers} />
          )}
        </div>
      )}
      {active &&
        checking &&
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
          <StateBadge tone="good">{t("checkFinished")}</StateBadge>
          <div>
            <Button onClick={onShowResult}>{t("showResult")}</Button>
          </div>
        </div>
      )}
      {!active && !measured && session.stop_reason !== "budget" && (
        <p className="text-muted-foreground text-sm">{t("checkSkipped")}</p>
      )}
      {runId && (
        <Link
          className="block text-sm underline underline-offset-4"
          href={`/agents/${session.agent_id}/evals/${runId}`}
          data-tour="improvement-open-check"
        >
          {t("openCheck")}
        </Link>
      )}
    </section>
  );
}

function RunStages({ runId, judging }: { runId: string; judging: boolean }) {
  const t = useTranslations("improvement");
  const { run, error, refetch } = useEvalRun(runId);
  if (error) return <StepError error={error} retry={refetch} />;
  if (!run) return <p role="status">{t("loading")}</p>;
  const state = stages(run, judging);
  return (
    <>
      <p className="text-sm">{t("checkQuestions", { count: run.cases })}</p>
      <Stepper
        label={t("checkTitle")}
        stages={(["asking", "grading", "repeating"] as const).map((stage) => ({
          id: stage,
          label: t(`checkStage.${stage}`, { count: run.attempts_total - run.first_total }),
          state: state[stage],
          stateLabel: t(`stepState.${state[stage]}`),
        }))}
      />
    </>
  );
}

/**
 * How far one side of the check has answered. Today's version and the changed one
 * are asked in the same run, so each gets its own bar rather than a step of its own.
 */
function AnswerBar({
  label,
  answers,
  note,
}: {
  label: string;
  answers: CheckAnswers;
  note?: string;
}) {
  const t = useTranslations("improvement");
  const { answered, total } = answers;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground tabular-nums">
          {t("checkBars.count", { answered, total })}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={answered}
        className="bg-muted h-2 overflow-hidden rounded-full"
      >
        <div
          className="bg-chart h-full rounded-full transition-[width] duration-500"
          style={{ width: `${total > 0 ? (answered / total) * 100 : 0}%` }}
        />
      </div>
      {note && <p className="text-muted-foreground text-xs">{note}</p>}
    </div>
  );
}
