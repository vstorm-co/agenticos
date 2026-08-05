/**
 * API client for skill changes an agent proposed.
 *
 * The body comes down whole, and that is deliberate: somebody deciding whether an
 * agent's rewrite of a policy becomes the policy has to read it. A listing that
 * carried only a name would make the decision a coin flip with an audit trail.
 */

import { apiClient } from "./api-client";

export type ProposalStatus = "pending" | "applied" | "discarded";

export interface SkillChangeRecord {
  id: string;
  /** The skill this edits; null for one the agent wrote from nothing. */
  skill_id: string | null;
  agent_id: string | null;
  /** Where it was written, so the exchange behind it can be read. */
  conversation_id: string | null;
  name: string;
  description: string;
  content: string;
  /** The resource files, as name to content. */
  resources: Record<string, string>;
  status: ProposalStatus;
  decided_by_user_id: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string | null;
}

interface SkillChangeList {
  items: SkillChangeRecord[];
  total: number;
}

const ROOT = "/skill-changes";

export async function listSkillChanges(status?: ProposalStatus): Promise<SkillChangeRecord[]> {
  const query = status === undefined ? "" : `?status=${status}`;
  const data = await apiClient.get<SkillChangeList>(`${ROOT}${query}`);
  return data.items;
}

/** Accept it. The skill is rewritten and every agent bound to it follows the new body. */
export async function applySkillChange(id: string): Promise<SkillChangeRecord> {
  return apiClient.post<SkillChangeRecord>(`${ROOT}/${id}/apply`);
}

/** Refuse it, keeping the record of what was proposed. */
export async function discardSkillChange(id: string): Promise<SkillChangeRecord> {
  return apiClient.post<SkillChangeRecord>(`${ROOT}/${id}/discard`);
}
