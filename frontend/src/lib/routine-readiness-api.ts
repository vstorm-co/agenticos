import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

/** Mirrors the backend's `RoutineBlockerCode`: one per check a fire makes. */
export type RoutineBlockerCode =
  | "creator_inactive"
  | "creator_cannot_run"
  | "agent_unavailable"
  | "ended"
  | "sources_setup"
  | "sources_review"
  | "routine_changed"
  | "platform_identity"
  | "awaiting_approval"
  | "awaiting_answer"
  | "budget_exhausted"
  | "actions_need_approval";

/**
 * One reason the next activation will not finish. `blocked`: no run starts.
 * `attention`: a run starts but waits on a person before it finishes.
 */
export interface RoutineBlocker {
  code: RoutineBlockerCode;
  severity: "blocked" | "attention";
  run_id: string | null;
  count: number | null;
}

/** What would stop a routine's next activation, evaluated as its creator - paused or not. */
export interface TriggerReadiness {
  trigger_id: string;
  blockers: RoutineBlocker[];
}

/**
 * A previous run waiting on a person. It holds a schedule's own activations
 * (`claim_due`), never a manual run: Run now deliberately fires past it.
 */
export const PARKED_CODES: ReadonlySet<RoutineBlockerCode> = new Set([
  "awaiting_approval",
  "awaiting_answer",
]);

/** Whether a manual run would be refused too, not only the routine's own activations. */
export function stopsRunNow(blocker: RoutineBlocker): boolean {
  return blocker.severity === "blocked" && !PARKED_CODES.has(blocker.code);
}

/** The server reads at most this many routines per request. */
export const READINESS_BATCH = 100;

export const routineReadinessApi = {
  /** One answer per routine the caller can see; the rest are left out, not refused. */
  list: (triggerIds: string[]) =>
    apiClient.post<{ items: TriggerReadiness[] }>("/triggers/readiness", {
      trigger_ids: triggerIds,
    }),
};

/** The blockers a listing already proves, shown until the readiness check answers. */
export function listedBlockers(trigger: Trigger): RoutineBlocker[] {
  const found: RoutineBlocker[] = [];
  if (trigger.paused_for_budget) {
    found.push({ code: "budget_exhausted", severity: "blocked", run_id: null, count: null });
  }
  if (trigger.setup_required) {
    found.push({ code: "sources_setup", severity: "blocked", run_id: null, count: null });
  }
  return found;
}
