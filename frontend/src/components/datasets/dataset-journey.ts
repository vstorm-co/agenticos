import { ungradedCases, scoringProblem } from "@/lib/scoring";
import type { Dataset } from "@/types/datasets";

export type DatasetNextStep = "cases" | "grading" | "evals";

/** Coverage, rather than an enabled-but-unused scorer, decides whether grading is ready. */
export function datasetNextStep(
  dataset: Pick<Dataset, "case_count" | "scoring" | "stats">,
): DatasetNextStep {
  if (dataset.case_count === 0) return "cases";
  if (
    scoringProblem(dataset.scoring) !== null ||
    ungradedCases(dataset.scoring, dataset.stats, dataset.scoring.checks.defaults.length) > 0
  )
    return "grading";
  return "evals";
}
