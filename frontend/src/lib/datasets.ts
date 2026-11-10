import type { Dataset } from "@/types/datasets";

/** Whether an eval can start on a dataset: one with a case, that this caller may run. */
export function isRunnable(dataset: Dataset): boolean {
  return dataset.case_count > 0 && dataset.can_run;
}
