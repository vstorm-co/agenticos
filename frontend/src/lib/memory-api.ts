/**
 * API client for the memory kept about a person.
 *
 * Two callers and one shape. A person reads their own store with no permission
 * to ask for, and a deployment administrator reads somebody else's by naming the
 * tenant and the person - never an organization role, because reading what every
 * agent has learned about a named colleague is a surveillance affordance and an
 * Owner is not the party a subject-access request reaches (#1594).
 */

import { apiClient } from "./api-client";

export interface MemoryNote {
  id: string;
  agent_id: string;
  agent_name: string | null;
  name: string;
  description: string | null;
  content: string;
  format: string;
  kind: string;
  created_at: string | null;
  updated_at: string | null;
  /** When the *agent* last wrote the content. Unmoved by a suppression. */
  written_at: string | null;
  /** Set while the note is suppressed - not listed, not read, not editable by any tool. */
  deactivated_at: string | null;
}

export interface MemoryPage {
  items: MemoryNote[];
  total: number;
}

const ROOT = "/memory";

export async function getMyMemory(skip = 0, limit = 50): Promise<MemoryPage> {
  return apiClient.get<MemoryPage>(`${ROOT}/mine?skip=${skip}&limit=${limit}`);
}

export async function setNoteActive(id: string, active: boolean): Promise<MemoryNote> {
  return apiClient.patch<MemoryNote>(`${ROOT}/mine/${id}`, { active });
}

export async function deleteNote(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/mine/${id}`);
}

/** One person's store in one tenant. Refused unless the caller is an app admin. */
export async function getPersonMemory(
  userId: string,
  organizationId: string,
  reason?: string,
  skip = 0,
  limit = 50,
): Promise<MemoryPage> {
  const query = new URLSearchParams({
    organization_id: organizationId,
    skip: String(skip),
    limit: String(limit),
  });
  if (reason) query.set("reason", reason);
  return apiClient.get<MemoryPage>(`${ROOT}/person/${userId}?${query}`);
}

export type ClaimStatus = "current" | "disputed" | "superseded" | "merged" | "retracted";

/** One recorded fact, preference or decision, with where it came from. */
export interface MemoryClaim {
  id: string;
  agent_id: string | null;
  agent_name: string | null;
  /** `profile` serves every agent acting for the person; `agent` is one agent's relationship. */
  scope: "profile" | "agent";
  subject: string | null;
  statement: string;
  kind: string;
  origin: "agent" | "person" | "consolidation";
  status: ClaimStatus;
  observed_at: string;
  effective_from: string | null;
  effective_to: string | null;
  supersedes_id: string | null;
  derived_from_count: number;
}

export interface MemoryClaimPage {
  items: MemoryClaim[];
  total: number;
}

export const CLAIMS_PAGE_SIZE = 100;

export async function getMyClaims(history: boolean, skip = 0): Promise<MemoryClaimPage> {
  return apiClient.get<MemoryClaimPage>(
    `${ROOT}/claims/mine?limit=${CLAIMS_PAGE_SIZE}&skip=${skip}&history=${history}`,
  );
}

/** Replace a claim with the person's own words; the old one stays in the history. */
export async function correctClaim(
  id: string,
  statement: string,
  effectiveFrom: string | null,
): Promise<MemoryClaim> {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/correct`, {
    statement,
    effective_from: effectiveFrom,
  });
}

/** Take a claim out of use. It and everything it came from stay in the history. */
export async function retractClaim(id: string): Promise<MemoryClaim> {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/retract`, {});
}
