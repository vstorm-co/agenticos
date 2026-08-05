/**
 * Types for GET /stats/usage and GET /ratings/summary - the dashboard's numbers.
 *
 * One composed response on purpose: the cards reading it share one query, one
 * loading state and one failure. A `group_by` request is a different question
 * about the same window and fills only its own section, leaving the composed
 * blocks null - which is why they are typed nullable.
 */

import type { RunStatus } from "./runs";

export type UsageScope = "org" | "own";

export interface DayCount {
  date: string;
  runs: number;
}

export interface SurfaceCount {
  surface: string;
  runs: number;
}

export interface AgentCount {
  agent_id: string;
  name: string;
  runs: number;
}

export interface StatusCount {
  status: RunStatus;
  runs: number;
}

export interface ModelCount {
  /** Null when the run recorded no label - its own row, never folded into a model. */
  model_label: string | null;
  runs: number;
}

export interface LatencyMs {
  /** Null when nothing in the window finished - distinct from a fast zero. */
  p50: number | null;
  p95: number | null;
}

export interface ActiveUsers {
  active: number;
  total_members: number;
}

export interface ProviderCost {
  provider: string | null;
  /** Serialised Decimal - never parse into a float for arithmetic. */
  cost_usd: string;
}

export interface CostBlock {
  /** Serialised Decimals; the calendar month-to-date figure lives on GET /spend. */
  period_usd: string;
  previous_period_usd: string;
  by_provider: ProviderCost[];
}

export interface VersionUsageRow {
  /** Null id with a null number is "a deleted version" - kept, the runs happened. */
  agent_version_id: string | null;
  version: number | null;
  runs: number;
  completed_runs: number;
  p95_ms: number | null;
  avg_cost_usd: string | null;
  like_count: number;
  rating_count: number;
}

export interface UsageStats {
  from: string;
  to: string;
  scope: UsageScope;
  total_runs: number | null;
  previous_total_runs: number | null;
  by_day: DayCount[] | null;
  by_surface: SurfaceCount[] | null;
  by_agent: AgentCount[] | null;
  by_status: StatusCount[] | null;
  by_model: ModelCount[] | null;
  latency_ms: LatencyMs | null;
  cost: CostBlock | null;
  /** scope=org only. */
  active_users: ActiveUsers | null;
  /** scope=own only: the caller's runs parked on somebody's decision. */
  pending_approvals: number | null;
  /** group_by=version only. */
  agent_id: string | null;
  by_version: VersionUsageRow[] | null;
}

export interface RatingsByDay {
  date: string;
  likes: number;
  dislikes: number;
}

/** Same bones as the admin summary so the chart ports, plus the window envelope. */
export interface RatingsSummary {
  from: string;
  to: string;
  scope: UsageScope;
  total_ratings: number;
  like_count: number;
  dislike_count: number;
  average_rating: number;
  with_comments: number;
  /** Sparse - days nobody rated are absent. */
  ratings_by_day: RatingsByDay[];
}
