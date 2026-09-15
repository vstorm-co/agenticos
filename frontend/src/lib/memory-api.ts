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
  /** Set while the note is suppressed - not listed, not read, not editable by any tool. */
  deactivated_at: string | null;
}

export interface MemoryPage {
  items: MemoryNote[];
  total: number;
  /**
   * Agents whose memories live in somebody else's service (mem0) and are not in
   * `items`. Named rather than left out: a page of native notes presented as a
   * complete inventory would be worse than saying what it misses.
   */
  external_stores: string[];
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
): Promise<MemoryPage> {
  const query = new URLSearchParams({ organization_id: organizationId });
  if (reason) query.set("reason", reason);
  return apiClient.get<MemoryPage>(`${ROOT}/person/${userId}?${query}`);
}
