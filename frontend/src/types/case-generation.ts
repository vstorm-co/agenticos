/**
 * Generated dataset cases - drafted by the case generator, decided by a person.
 *
 * Mirrors `app/schemas/case_generation.py`. A proposal is a case's content plus
 * where it was drafted from; it waits outside the dataset until accepted.
 */

import type { DatasetCaseContent } from "./datasets";

/** What a case is drafted from - one per source a person can pick. */
export type CaseOrigin = "agent" | "knowledge" | "conversation" | "red_team";
export type GenerationStatus = "running" | "ready" | "failed";

export const CASE_ORIGINS: CaseOrigin[] = ["agent", "knowledge", "conversation", "red_team"];

export interface CaseGeneration {
  id: string;
  agent_id: string | null;
  sources: CaseOrigin[];
  requested_count: number;
  status: GenerationStatus;
  error: string | null;
  /** The generator's run, with its cost, in Activity. */
  run_id: string | null;
  proposed_count: number;
  accepted_count: number;
  dismissed_count: number;
  created_at: string;
  finished_at: string | null;
}

export interface CaseGenerationList {
  items: CaseGeneration[];
}

export interface CaseProposal extends DatasetCaseContent {
  id: string;
  generation_id: string;
  origin: CaseOrigin;
  source_document_id: string | null;
  source_run_id: string | null;
  source_conversation_id: string | null;
  source_message_id: string | null;
  created_at: string;
}

export interface CaseProposalList {
  items: CaseProposal[];
  total: number;
}

/** What a person asks to have drafted. */
export interface CaseGenerationRequest {
  agent_id: string;
  sources: CaseOrigin[];
  count: number;
}

/** How many cases one source will be asked for, and how much it has to draft from. */
export interface SourcePlan {
  source: CaseOrigin;
  cases: number;
  /** Passages for knowledge, questions for conversations, tools for the agent; 0 for red team. */
  material: number;
}

/** What a generation would draft and roughly cost, before anything is spent. */
export interface CaseGenerationEstimate {
  count: number;
  sources: SourcePlan[];
  /** Knowledge bases the agent uses that the caller may not read. */
  excluded_collections: number;
  /** An estimate in USD; null for a model with no known price. */
  estimated_cost_usd: string | null;
}
