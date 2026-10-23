"use client";

import { useTranslations } from "next-intl";

import type { EvalRun } from "@/types/eval-runs";

/**
 * What the run did with its grading on its own: how many answers it sent to
 * review - the regressions it confirmed and the ones the judge failed to
 * grade - and how many older ones still waiting on their cases they replaced,
 * or why it could not; that a check of a proposal sends nothing by itself; and
 * a warning when the judge graded the model it runs on.
 */
export function JudgeNotes({ run }: { run: EvalRun }) {
  const t = useTranslations("evals.review");
  const tScoring = useTranslations("datasets.scoring");
  const graded = run.arms.find(
    (arm) =>
      run.judge_model_profile_id !== null && arm.model_profile_id === run.judge_model_profile_id,
  );
  return (
    <>
      {run.routing_error && (
        <p className="text-warning text-sm">
          {t("routingFailed", { reason: run.routing_error.message })}
        </p>
      )}
      {run.routed_to_review > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("routed", { count: run.routed_to_review, replaced: run.routed_replacing })}
        </p>
      )}
      {run.proposal_check && <p className="text-muted-foreground text-sm">{t("checkHeld")}</p>}
      {graded && (
        <p className="text-warning text-sm">
          {tScoring("judgeSameModel", { model: graded.model_label })}
        </p>
      )}
    </>
  );
}
