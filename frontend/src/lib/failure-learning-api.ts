/**
 * API client for the failure-learning loop,
 * `backend/app/api/routes/v1/failure_learning.py`. Thin wrappers over
 * `apiClient`, one per route; `use-failure-learning.ts` calls these,
 * components never do. Field names stay snake_case, as the API answers
 * them - the rest of the console does the same for workflow evals.
 */

import { apiClient } from "@/lib/api-client";
import type { AgentRun } from "@/types/runs";

export type LedgerScope = "agent" | "model";
export type LedgerStatus = "draft" | "open" | "dismissed" | "resolved";
export type ProposalStatus = "draft" | "applied" | "rejected";
export type ProposalTargetType = "instructions" | "skill";

/** One recurring failure, counted live over real runs in a window. */
export interface FailurePattern {
  agent_id: string | null;
  agent_name: string | null;
  model: string | null;
  status: string;
  error_class: string;
  pattern_key: string;
  count: number;
  first_seen: string | null;
  last_seen: string | null;
  sample_run_ids: string[];
  sample_message_ids: string[];
  already_tracked: boolean;
}

/** Mined patterns, and what the mining cannot see. */
export interface FailurePatternList {
  items: FailurePattern[];
  total: number;
  notes: string[];
}

export interface LedgerEntryCreate {
  scope: LedgerScope;
  model?: string | null;
  pattern_key: string;
  title: string;
  summary: string;
  evidence: Record<string, unknown>;
}

export interface LedgerEntryUpdate {
  status?: LedgerStatus;
  summary?: string;
}

/** One curated pattern, with how much work hangs off it. */
export interface LedgerEntryRead {
  id: string;
  organization_id: string;
  agent_id: string | null;
  scope: LedgerScope;
  model: string | null;
  pattern_key: string;
  title: string;
  summary: string;
  evidence: Record<string, unknown>;
  status: LedgerStatus;
  created_by_user_id: string | null;
  eval_case_count: number;
  proposal_count: number;
  open_since: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LedgerEntryList {
  items: LedgerEntryRead[];
  total: number;
}

export interface EvalCaseInput {
  message: string;
  history?: { role: "user" | "assistant"; text: string }[];
}

export interface EvalExpectation {
  kind: "equals" | "contains" | "not_contains";
  field: "text" | "status";
  value: string;
}

export interface EvalCaseCreate {
  ledger_entry_id?: string | null;
  name: string;
  input: EvalCaseInput;
  expectation: EvalExpectation;
  model_profile_id?: string | null;
  source_run_id?: string | null;
}

/** How the agent's latest try went for this one case, or null when untried. */
export interface EvalCaseLatestTry {
  try_id: string;
  old_passed: boolean | null;
  new_passed: boolean | null;
  gate_passed: boolean | null;
  status: string;
}

/** One reproduction of a real bad experience. */
export interface EvalCaseRead {
  id: string;
  agent_id: string;
  ledger_entry_id: string | null;
  name: string;
  position: number;
  input: EvalCaseInput;
  expectation: EvalExpectation;
  model_profile_id: string | null;
  source_run_id: string | null;
  created_by_user_id: string | null;
  latest_try: EvalCaseLatestTry | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EvalCaseList {
  items: EvalCaseRead[];
  total: number;
}

export interface EvalTryCreate {
  case_ids: string[];
  proposal_id?: string | null;
  instructions_override?: string | null;
  samples?: number;
}

/** One case as its runs stand now: still going, answered, or failed. */
export interface EvalTryCaseRead {
  eval_id: string;
  name: string;
  expectation: EvalExpectation;
  old_run_ids: string[];
  new_run_ids: string[];
  old_passed: boolean | null;
  new_passed: boolean | null;
  gate_passed: boolean | null;
  status: string;
  reason: string | null;
}

/** One try of a set of cases, judged as its runs stand now. */
export interface EvalTryRead {
  id: string;
  agent_id: string;
  proposal_id: string | null;
  /** Set when the try was run against a skill's new text. */
  target_skill_id: string | null;
  /** SHA-256 of the exact text the try ran; a skill apply must match it. */
  tested_content_sha256: string | null;
  created_at: string | null;
  cases: EvalTryCaseRead[];
  passed: number;
  failed: number;
  pending: number;
  gate_passed: boolean | null;
}

export interface ProposalCreate {
  ledger_entry_id?: string | null;
  eval_try_id?: string | null;
  target: { type: ProposalTargetType; skill_id?: string | null };
  old_text: string;
  new_text: string;
  rationale: string;
  base_agent_version_id?: string | null;
}

/** One proposed rule-text change, its eval evidence, and its apply record. */
export interface ProposalRead {
  id: string;
  organization_id: string;
  agent_id: string;
  ledger_entry_id: string | null;
  eval_try_id: string | null;
  target_type: ProposalTargetType;
  skill_id: string | null;
  old_text: string;
  new_text: string;
  rationale: string;
  base_agent_version_id: string | null;
  base_content_sha256: string | null;
  applied_content_sha256: string | null;
  reverted_at: string | null;
  /** A skill apply that can still be reverted once, from its saved content. */
  rollback_available: boolean;
  status: ProposalStatus;
  applied_version_id: string | null;
  created_by_user_id: string | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  eval_evidence: EvalTryRead | null;
  applied_version: { id: string; number: number } | null;
  /** Whether an eval gate evidences this proposal. Set for both target types. */
  eval_gated: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProposalList {
  items: ProposalRead[];
  total: number;
}

const agentBase = (agentId: string) => `/agents/${agentId}/failure-learning`;

/** Org-wide patterns, grouped by agent, model, status and error class. */
export async function listOrgPatterns(): Promise<FailurePatternList> {
  return apiClient.get<FailurePatternList>("/failure-learning/patterns");
}

/** One agent's patterns in the last 7 days. */
export async function listAgentPatterns(agentId: string): Promise<FailurePatternList> {
  return apiClient.get<FailurePatternList>(`${agentBase(agentId)}/patterns`);
}

/** An agent's ledger entries, newest first, with model-scoped entries beside them. */
export async function listLedgerEntries(
  agentId: string,
  status?: LedgerStatus,
): Promise<LedgerEntryList> {
  return apiClient.get<LedgerEntryList>(`${agentBase(agentId)}/ledger`, {
    params: status ? { status } : undefined,
  });
}

/** Curate a pattern into a draft ledger entry. */
export async function createLedgerEntry(
  agentId: string,
  input: LedgerEntryCreate,
): Promise<LedgerEntryRead> {
  return apiClient.post<LedgerEntryRead>(`${agentBase(agentId)}/ledger`, input);
}

/** One ledger entry, with its case and proposal counts. */
export async function getLedgerEntry(agentId: string, entryId: string): Promise<LedgerEntryRead> {
  return apiClient.get<LedgerEntryRead>(`${agentBase(agentId)}/ledger/${entryId}`);
}

/** Accept, dismiss, or rewrite a ledger entry. Resolving is the apply's job. */
export async function updateLedgerEntry(
  agentId: string,
  entryId: string,
  input: LedgerEntryUpdate,
): Promise<LedgerEntryRead> {
  return apiClient.patch<LedgerEntryRead>(`${agentBase(agentId)}/ledger/${entryId}`, input);
}

/** Remove a ledger entry. Its eval cases keep what they said. */
export async function deleteLedgerEntry(agentId: string, entryId: string): Promise<void> {
  await apiClient.delete(`${agentBase(agentId)}/ledger/${entryId}`);
}

/**
 * Track a mined pattern: curate it into a draft entry under its agent.
 *
 * A model-scoped pattern names no agent, so the entry is anchored on the
 * agent of its first sample run - the entry itself stays model-scoped, the
 * anchor only satisfies the route's permission check, the same anchor the
 * daily digest uses.
 */
export async function trackPattern(
  pattern: FailurePattern,
  input: Omit<LedgerEntryCreate, "scope" | "model" | "pattern_key" | "evidence">,
): Promise<LedgerEntryRead> {
  const agentId = pattern.agent_id ?? (await resolvePatternAgent(pattern));
  return createLedgerEntry(agentId, {
    ...input,
    scope: pattern.agent_id === null ? "model" : "agent",
    model: pattern.model,
    pattern_key: pattern.pattern_key,
    evidence: {
      run_ids: pattern.sample_run_ids,
      message_ids: pattern.sample_message_ids,
      count: pattern.count,
      window: { from: pattern.first_seen, to: pattern.last_seen },
      error_class: pattern.error_class,
    },
  });
}

async function resolvePatternAgent(pattern: FailurePattern): Promise<string> {
  const firstRun = pattern.sample_run_ids[0];
  // i18n-exempt: developer diagnostic, caught by the caller and never shown.
  if (!firstRun) throw new Error("pattern has no sample run to anchor on");
  const run = await apiClient.get<AgentRun>(`/runs/${firstRun}`);
  return run.agent_id;
}

/** An agent's eval cases, oldest first, each with its latest try's verdict. */
export async function listEvalCases(agentId: string): Promise<EvalCaseList> {
  return apiClient.get<EvalCaseList>(`${agentBase(agentId)}/eval-cases`);
}

/** Add an eval case: an input, and what its answer should say. */
export async function createEvalCase(
  agentId: string,
  input: EvalCaseCreate,
): Promise<EvalCaseRead> {
  return apiClient.post<EvalCaseRead>(`${agentBase(agentId)}/eval-cases`, input);
}

/** Remove an eval case. Tries already made keep what they said then. */
export async function deleteEvalCase(agentId: string, caseId: string): Promise<void> {
  await apiClient.delete(`${agentBase(agentId)}/eval-cases/${caseId}`);
}

/** Start a try: each case twice per sample, old text against new. */
export async function startEvalTry(agentId: string, input: EvalTryCreate): Promise<EvalTryRead> {
  return apiClient.post<EvalTryRead>(`${agentBase(agentId)}/eval-runs`, input);
}

/** One try, its verdicts judged as its runs stand now. */
export async function getEvalTry(agentId: string, tryId: string): Promise<EvalTryRead> {
  return apiClient.get<EvalTryRead>(`${agentBase(agentId)}/eval-runs/${tryId}`);
}

/** An agent's proposals, newest first. */
export async function listProposals(
  agentId: string,
  status?: ProposalStatus,
): Promise<ProposalList> {
  return apiClient.get<ProposalList>(`${agentBase(agentId)}/proposals`, {
    params: status ? { status } : undefined,
  });
}

/** Propose one rule-text change, with the try that evidences it. */
export async function createProposal(
  agentId: string,
  input: ProposalCreate,
): Promise<ProposalRead> {
  return apiClient.post<ProposalRead>(`${agentBase(agentId)}/proposals`, input);
}

/** One proposal, with its eval evidence and its apply record. */
export async function getProposal(agentId: string, proposalId: string): Promise<ProposalRead> {
  return apiClient.get<ProposalRead>(`${agentBase(agentId)}/proposals/${proposalId}`);
}

/**
 * Apply a proposal: publish its new text, audited. Applying is the approval,
 * so this is the one call the caller must hold `agents:publish` (or
 * `skills:edit` for a skill target) to make.
 */
export async function applyProposal(agentId: string, proposalId: string): Promise<ProposalRead> {
  return apiClient.post<ProposalRead>(`${agentBase(agentId)}/proposals/${proposalId}/apply`);
}

/**
 * Revert a skill apply once: restore the content it saved, unless the skill
 * changed since it applied. Needs `skills:edit` on the skill.
 */
export async function revertProposal(agentId: string, proposalId: string): Promise<ProposalRead> {
  return apiClient.post<ProposalRead>(`${agentBase(agentId)}/proposals/${proposalId}/revert`);
}

/** Reject a proposal, with the reason recorded in the audit trail. */
export async function rejectProposal(
  agentId: string,
  proposalId: string,
  reason: string,
): Promise<ProposalRead> {
  return apiClient.post<ProposalRead>(`${agentBase(agentId)}/proposals/${proposalId}/reject`, {
    reason,
  });
}
