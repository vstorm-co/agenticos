"use client";

import { TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import type { DatasetScoring } from "@/types/scoring";
import type { CaseDraft } from "./case-form";

/**
 * Which of the dataset's scorers would grade this case as it is written, from
 * the dataset's Grading: said under the form, and warned of when it is nothing.
 */
export function CaseGradedBy({ scoring, draft }: { scoring: DatasetScoring; draft: CaseDraft }) {
  const t = useTranslations("datasets.scoring");
  const locale = useLocale();
  const { checks, trajectory, judge, reference } = scoring;
  const graders = [
    checks.enabled && (draft.checks.length > 0 || checks.defaults.length > 0)
      ? t("scorer.check")
      : null,
    trajectory.enabled && draft.expected_tool_calls.some((call) => call.tool.trim() !== "")
      ? t("scorer.trajectory")
      : null,
    judge.enabled && judge.criteria.length > 0
      ? t("gradedByJudge", { criteria: judge.criteria.map((c) => c.name).join(", ") })
      : null,
    reference.enabled && draft.reference_answer.trim() !== "" ? t("scorer.reference") : null,
  ].filter((grader): grader is string => grader !== null);

  if (graders.length === 0) {
    return (
      <p
        role="status"
        className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400"
      >
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        {t("gradedByNothing")}
      </p>
    );
  }
  return (
    <p className="text-muted-foreground text-xs">
      {t("gradedBy", {
        graders: new Intl.ListFormat(locale, { type: "conjunction" }).format(graders),
      })}
    </p>
  );
}
