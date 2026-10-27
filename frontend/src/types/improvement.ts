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
  knowledge_usd?: string;
  eval_usd: string;
  per_round_usd: string;
  total_usd: string;
  max_iterations: number;
  cases: number;
  evidence_runs: number;
  /** About how long the session takes if every round runs. */
  estimated_minutes: number;
  affordable: boolean;
  reason: string | null;
}
/** How far one side of a check has answered; a reused side answered in an earlier run. */
export interface CheckAnswers {
  answered: number;
  total: number;
  reused?: boolean;
}
export interface ImprovementIteration {
  id: string;
  number: number;
  authoring_request_id: string | null;
  batch_id: string | null;
  eval_run_ids: string[];
  candidate_spec_hash: string | null;
  included_hunk_ids?: string[] | null;
  previous_eval_run_ids?: string[];
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
  published_version_id?: string | null;
  published_version?: number | null;
  next_version?: number | null;
  offer_automatic_check?: boolean;
  can_restart?: boolean;
  can_discard?: boolean;
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
  /** Knowledge documents set aside with Not now in this session. */
  deferred_topic_ids?: string[];
  /** How far the first attempt's check has asked the agent as it is today. */
  baseline_answers?: CheckAnswers | null;
  /** How far the current attempt's check has asked the changed agent. */
  candidate_answers?: CheckAnswers | null;
  /** Whether the test told the versions apart; absent while working or without runs:view. */
  measurement_noise?: MeasurementNoise | null;
  timeline: {
    action: string;
    at: string;
    stage: string | null;
    status: string | null;
    reason: string | null;
    /** The person whose action this was; absent for the session's own steps. */
    actor_user_id?: string | null;
    /** Their name, for a reader who may see the member directory. */
    actor_name?: string | null;
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

export interface ImprovementEvidenceItem {
  run_id: string;
  conversation_id: string | null;
  kind: "chat" | "train_eval";
  status: string;
  rating: number;
  question: string | null;
  answer: string | null;
  comments: string[];
  branch: "agent" | "missing_knowledge" | "not_a_problem" | "unknown";
  reason: string | null;
  /** The knowledge gap topic its miss joined; examples sharing one are one problem. */
  topic_id?: string | null;
}
export interface ImprovementEvidence {
  items: ImprovementEvidenceItem[];
  sample_limit: number;
  training_failures: number;
}

export interface SelectionEstimate {
  suggestions: number;
  total_usd: string;
  affordable: boolean;
  candidate_hash: string;
}

export interface ContinuationEstimate {
  mode: "next_round" | "resume" | "retry";
  number: number;
  total_usd: string;
  budget_usd: string;
  affordable: boolean;
  candidate_hash: string;
}

/** One held-out question's grades in one attempt, the first answer then each re-ask. */
export interface NoisyAttempt {
  number: number;
  baseline: (boolean | null)[];
  candidate: (boolean | null)[];
}

/** Whether a session's checks could tell a better version from a worse one. */
export interface MeasurementNoise {
  noisy: boolean;
  held_out: number;
  baseline_low: number | null;
  baseline_high: number | null;
  baseline_spread: number;
  unstable: number;
  by_attempt: { number: number; baseline_unstable: number; candidate_unstable: number }[];
  examples: { case_id: string; input: string; attempts: NoisyAttempt[] }[];
}
