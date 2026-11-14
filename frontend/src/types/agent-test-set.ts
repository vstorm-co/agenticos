/** An agent's test set: what building it asks for, and what it made. */

export interface AgentTestSetRequest {
  /** Take the answers rated since then; every rating when absent. */
  since?: string;
  /** Write this many questions more, whatever the test set holds. */
  more?: number;
}

export interface AgentTestSetCounts {
  rated_good: number;
  rated_bad: number;
  skipped: number;
  /** Questions taken from other people's conversations. */
  from_others: number;
  generated_requested: number;
}

export interface AgentTestSetJudge {
  /** The dataset's own judge; null for the default judge. */
  agent_id: string | null;
  independent: boolean;
  /** Why it is not independent, in words for the person. */
  reason: string | null;
  reason_code: "one_model" | "ai_off" | "cannot_publish" | "unknown_model" | "shares_model" | null;
}

export interface AgentTestSetBootstrap {
  dataset_id: string;
  version: number;
  created: boolean;
  counts: AgentTestSetCounts;
  /** The generation writing more questions; they join the test set when it is ready. */
  generation_id: string | null;
  generation_skipped: "enough" | "ai_off" | "unavailable" | "nothing_to_draft" | null;
  judge: AgentTestSetJudge;
  /** Questions that can measure a change, not counting those still being written. */
  gradable: number;
  too_few: boolean;
}

export interface AgentTestSetEstimate {
  /** A serialised Decimal. */
  cost_usd: string;
  priced: boolean;
  generate: number;
}
