/** Durable improvement sessions; question and answer text stays behind runs:view. */
export type ImprovementStatus =
  | "queued"
  | "running"
  | "ready"
  | "stopped"
  | "failed"
  | "cancelled"
  | "stale"
  | "accepted"
  | "published"
  | "rejected";
export type ImprovementStage =
  "analyzing" | "classifying" | "drafting" | "proposing" | "filtering" | "evaluating" | "judging";
export interface ImprovementTarget {
  dataset_id?: string;
  suite_id?: string;
  improver_agent_id?: string;
  window_days?: number;
  max_iterations?: number;
}
export interface ImprovementEstimate {
  proposal_usd: string;
  eval_usd: string;
  per_round_usd: string;
  total_usd: string;
  max_iterations: number;
  cases: number;
  evidence_runs: number;
  affordable: boolean;
  reason: string | null;
}
export interface ImprovementIteration {
  id: string;
  number: number;
  authoring_request_id: string | null;
  batch_id: string | null;
  eval_run_ids: string[];
  candidate_spec_hash: string | null;
  attribution_eval_run_ids: Record<string, string>;
  dropped_hunk_ids: string[];
  dropped: { hunk_id: string; reason: string }[];
  verdict: "better" | "no_change" | "regression" | "inconclusive" | null;
  verdict_detail: Record<string, string | number | null> | null;
  cost_usd: string;
  started_at: string;
  ended_at: string | null;
}
export interface Improvement {
  id: string;
  agent_id: string;
  created_by_user_id: string | null;
  improver_agent_id: string | null;
  status: ImprovementStatus;
  stage: ImprovementStage | null;
  iteration: number;
  max_iterations: number;
  base_version_id: string | null;
  dataset_id: string;
  dataset_version: number;
  suite_id: string | null;
  estimate_usd: string;
  budget_usd: string;
  spent_usd: string;
  best_iteration_id: string | null;
  stop_reason: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  iterations: ImprovementIteration[];
  knowledge_eval_run_ids?: string[];
  timeline: {
    action: string;
    at: string;
    stage: string | null;
    status: string | null;
    reason: string | null;
  }[];
}
export interface AttributionEstimate {
  changes: number;
  total_usd: string;
  affordable: boolean;
  already_started: boolean;
}

export interface KnowledgeCheckTarget {
  mode?: "context" | "retrieval";
  topic_id: string;
  round: number;
  case_ids: string[];
}
export interface KnowledgeCheckEstimate {
  total_usd: string;
  affordable: boolean;
  can_measure: boolean;
  cases: number;
  excluded: number;
  supported: boolean;
  draft_hash: string;
  reason: string | null;
}
