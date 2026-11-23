"use client";

import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { listedBlockers, routineReadinessApi } from "@/lib/routine-readiness-api";
import type { Trigger } from "@/types/triggers";

/**
 * What would stop a routine's next activation. Read per routine, beside the
 * listing rather than inside it: the server answers with the checks a fire makes,
 * which cost more than a listing should. Until it answers, the blockers the
 * listing itself proves stand in. Any trigger write invalidates it through the
 * shared `qk.triggers.all()` prefix.
 */
export function useRoutineReadiness(trigger: Trigger) {
  const { data } = useQuery({
    queryKey: qk.triggers.readiness(trigger.agent_id, trigger.id),
    queryFn: () => routineReadinessApi.get(trigger.agent_id, trigger.id),
    staleTime: 30_000,
  });
  return data?.blockers ?? listedBlockers(trigger);
}
