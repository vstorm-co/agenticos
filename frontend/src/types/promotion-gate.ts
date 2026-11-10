import type { EvalSuiteResult } from "@/types/eval-suites";

/**
 * Where one guard stands on a version. `passed` is the only state that lets the
 * version through; `stale` is a result over another dataset version or
 * threshold than the suite holds now or another serving baseline, `paused` a suite that will produce no
 * result until it is resumed, and `unpinned` a guard not pinned to a dataset
 * version yet, which lets nothing through until it is.
 */
export type GuardState =
  | "passed"
  | "failed"
  | "inconclusive"
  | "skipped"
  | "error"
  | "checking"
  | "stale"
  | "unchecked"
  | "paused"
  | "unpinned";

export interface PromotionGuard {
  suite_id: string;
  suite_name: string;
  state: GuardState;
  paused_reason: string | null;
  /** The result the state was read from: the last settled one, or the open one. */
  result: EvalSuiteResult | null;
}

/** Whether a version may be promoted onto an environment, guard by guard. */
export interface PromotionGate {
  environment_id: string;
  environment_name: string;
  version_id: string;
  version: number;
  guarded: boolean;
  passing: boolean;
  /** Whether the caller may promote past the guards that did not pass. */
  can_override: boolean;
  guards: PromotionGuard[];
}

export interface PromotionGateRun {
  started: string[];
  gate: PromotionGate;
}

/** One guard as it stood when it was overridden. */
export interface PromotionGuardRecord {
  suite_id: string;
  suite_name: string;
  state: GuardState;
  result_id: string | null;
}

/** A version promoted onto a guarded environment past guards that had not passed. */
export interface PromotionOverride {
  id: string;
  environment_id: string | null;
  environment_name: string;
  user_id: string | null;
  /** Null once the person who overrode has left the organization. */
  user_email: string | null;
  reason: string;
  guards: PromotionGuardRecord[];
  created_at: string;
}
