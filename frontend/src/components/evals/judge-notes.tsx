"use client";

import { useTranslations } from "next-intl";

import type { EvalRun } from "@/types/eval-runs";

/**
 * What the run did with its grading on its own: how many answers it sent to
 * review - the regressions it confirmed and the ones the judge could not
 * grade - and a warning when the judge graded the model it runs on.
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
      {run.routed_to_review > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("routed", { count: run.routed_to_review })}
        </p>
      )}
      {graded && (
        <p className="text-warning text-sm">
          {tScoring("judgeSameModel", { model: graded.model_label })}
        </p>
      )}
    </>
  );
}
