"use client";

import { useEvalRun } from "@/hooks/use-eval-runs";
import { VerdictChip } from "./run-row";

/**
 * An eval run's verdict as the chip its own list shows, read on its own - for a
 * screen that names the run but not how it came out. Nothing until the run is
 * read, or when it cannot be.
 */
export function EvalRunVerdict({ runId }: { runId: string }) {
  const { run } = useEvalRun(runId);
  return run ? <VerdictChip run={run} /> : null;
}
