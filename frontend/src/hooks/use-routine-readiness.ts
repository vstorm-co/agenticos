"use client";

import { useQueries } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import {
  listedBlockers,
  READINESS_BATCH,
  routineReadinessApi,
  type RoutineBlocker,
} from "@/lib/routine-readiness-api";
import type { Trigger } from "@/types/triggers";

/**
 * What would stop each routine's next activation, read once for a whole screen.
 * Beside the listing rather than inside it: the server answers with the checks a
 * fire makes, which cost more than a listing should. Until it answers, or when it
 * cannot, the blockers the listing itself proves stand in. Trigger writes refresh
 * it through `qk.triggers.all()`; runs, agents and memberships through
 * `qk.triggers.readinessAll()`.
 */
export function useRoutinesReadiness(triggers: Trigger[]) {
  const ids = triggers.map((trigger) => trigger.id).sort();
  const batches: string[][] = [];
  for (let start = 0; start < ids.length; start += READINESS_BATCH) {
    batches.push(ids.slice(start, start + READINESS_BATCH));
  }
  const answers = useQueries({
    queries: batches.map((batch) => ({
      queryKey: qk.triggers.readiness(batch),
      queryFn: () => routineReadinessApi.list(batch),
      staleTime: 30_000,
    })),
  });
  const known = new Map<string, RoutineBlocker[]>();
  for (const answer of answers) {
    for (const item of answer.data?.items ?? []) known.set(item.trigger_id, item.blockers);
  }
  return (trigger: Trigger): RoutineBlocker[] => known.get(trigger.id) ?? listedBlockers(trigger);
}
