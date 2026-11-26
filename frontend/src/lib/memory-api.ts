/**
 * API client for the memory kept about a person.
 *
 * Two callers and one shape. A person reads their own store with no permission
 * to ask for, and a deployment administrator reads somebody else's by naming the
 * tenant and the person - never an organization role, because reading what every
 * agent has learned about a named colleague is a surveillance affordance and an
 * Owner is not the party a subject-access request reaches (#1594).
 */

import type { DatasetCase } from "@/types/datasets";
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

export async function getMyMemory(skip = 0, limit = 50, q = ""): Promise<MemoryPage> {
  return apiClient.get<MemoryPage>(
    `${ROOT}/mine?skip=${skip}&limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
  );
}

export async function setNoteActive(id: string, active: boolean): Promise<MemoryNote> {
  return apiClient.patch<MemoryNote>(`${ROOT}/mine/${id}`, { active });
}

export async function editNoteContent(note: MemoryNote, content: string): Promise<MemoryNote> {
  return apiClient.patch<MemoryNote>(`${ROOT}/mine/${note.id}/content`, {
    content,
    expected_updated_at: note.updated_at,
  });
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
export interface DecisionEpisode {
  situation: string;
  choice: string;
  alternatives: string[];
  expected_outcome: string | null;
  actual_outcome: string | null;
  correction: string | null;
}

export async function reviewDecisionCase(
  id: string,
  datasetId: string,
  input: string,
  referenceAnswer: string,
): Promise<DatasetCase> {
  return apiClient.post<DatasetCase>(`${ROOT}/claims/mine/${id}/improve-case`, {
    confirmed: true,
    dataset_id: datasetId,
    input,
    reference_answer: referenceAnswer,
  });
}

export interface MemoryClaim {
  id: string;
  agent_id: string | null;
  agent_name: string | null;
  /** `profile` serves every agent acting for the person; `agent` is one agent's relationship. */
  scope: "profile" | "agent" | "organization" | "group";
  subject: string | null;
  object_id?: string | null;
  value?: string | number | boolean | null;
  statement: string;
  kind: string;
  origin: "agent" | "person" | "consolidation";
  status: ClaimStatus;
  observed_at: string;
  effective_from: string | null;
  effective_to: string | null;
  supersedes_id: string | null;
  derived_from_count: number;
  episode?: DecisionEpisode | null;
}

export interface MemoryClaimPage {
  items: MemoryClaim[];
  total: number;
}

export const CLAIMS_PAGE_SIZE = 100;

export interface MemoryClaimFilters {
  q?: string;
  kind?: "fact" | "preference" | "decision";
  scope?: "profile" | "agent";
}

export async function getMyClaims(
  history: boolean,
  skip = 0,
  filters: MemoryClaimFilters = {},
): Promise<MemoryClaimPage> {
  const params = new URLSearchParams({
    limit: String(CLAIMS_PAGE_SIZE),
    skip: String(skip),
    history: String(history),
  });
  if (filters.q) params.set("q", filters.q);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.scope) params.set("scope", filters.scope);
  return apiClient.get<MemoryClaimPage>(`${ROOT}/claims/mine?${params}`);
}

/** Replace a claim with the person's own words; the old one stays in the history. */
export async function correctClaim(
  id: string,
  statement: string,
  effectiveFrom: string | null,
  episode?: DecisionEpisode,
): Promise<MemoryClaim> {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/correct`, {
    statement,
    effective_from: effectiveFrom,
    ...(episode ? { episode } : {}),
  });
}

/** Take a claim out of use. It and everything it came from stay in the history. */
export async function retractClaim(id: string): Promise<MemoryClaim> {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/retract`, {});
}

export type MemoryLibrary = "personal" | "organization";
export type MemoryObjectKind = "person" | "company" | "project" | "commitment";

export interface MemoryObject {
  id: string;
  kind: MemoryObjectKind;
  name: string;
}

export interface MemoryCursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface MemoryTimeline extends MemoryCursorPage<MemoryClaim> {
  object: MemoryObject;
}

export interface MemoryClaimDetail extends MemoryClaim {
  evidence: Array<{
    kind: "message" | "gmail";
    source_id: string;
    quote: string;
    occurred_at: string;
  }>;
  sources: MemoryClaim[];
  superseded: MemoryClaim | null;
  withheld: number;
}

export interface SharedMemoryNote {
  id: string;
  name: string;
  content: string;
}

export function getMemoryObjects(
  library: MemoryLibrary,
  q: string,
  kind: MemoryObjectKind | "all",
  cursor: string | null,
) {
  const query = new URLSearchParams({ library, q });
  if (kind !== "all") query.set("kind", kind);
  if (cursor) query.set("cursor", cursor);
  return apiClient.get<MemoryCursorPage<MemoryObject>>(`${ROOT}/objects?${query}`);
}

export function getMemoryTimeline(
  library: MemoryLibrary,
  objectId: string,
  asOf: string,
  knownAt: string,
  cursor: string | null,
) {
  const query = new URLSearchParams({ library });
  if (asOf) query.set("as_of", `${asOf}T00:00:00Z`);
  if (asOf && knownAt) query.set("known_at", `${knownAt}T23:59:59.999999Z`);
  if (cursor) query.set("cursor", cursor);
  return apiClient.get<MemoryTimeline>(`${ROOT}/objects/${objectId}?${query}`);
}

export function getMemoryClaimDetail(library: MemoryLibrary, id: string) {
  const location = library === "personal" ? "mine" : "shared";
  return apiClient.get<MemoryClaimDetail>(`${ROOT}/claims/${location}/${id}`);
}

export function getSharedClaims(q: string, skip: number) {
  const query = new URLSearchParams({ q, skip: String(skip) });
  return apiClient.get<MemoryClaimPage>(`${ROOT}/claims/shared?${query}`);
}

export function getSharedNotes(cursor: string | null) {
  const query = new URLSearchParams(cursor ? { cursor } : {});
  return apiClient.get<MemoryCursorPage<SharedMemoryNote>>(`${ROOT}/notes/shared?${query}`);
}

export function shareMemoryClaim(id: string, groupId: string | null) {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/share`, {
    confirmed: true,
    group_id: groupId,
  });
}

export function shareMemoryNote(note: MemoryNote, groupId: string | null) {
  return apiClient.post<SharedMemoryNote>(`${ROOT}/mine/${note.id}/share`, {
    confirmed: true,
    group_id: groupId,
    expected_updated_at: note.updated_at,
  });
}

export interface MemoryMailRule {
  sender: string;
  subject: string;
  commitment: string;
  mode: "shadow" | "active";
  notify: boolean;
}

export interface MemoryMailState extends MemoryMailRule {
  authorized: boolean;
  last_outcome: "daily_limit" | "withheld" | "shadow" | "late" | "unchanged" | "applied" | null;
}

export function getMemoryMailRule() {
  return apiClient.get<MemoryMailState | null>(`${ROOT}/sources/gmail`);
}

export function saveMemoryMailRule(rule: MemoryMailRule) {
  return apiClient.put<MemoryMailState>(`${ROOT}/sources/gmail`, { ...rule, confirmed: true });
}

export function removeMemoryMailRule() {
  return apiClient.delete(`${ROOT}/sources/gmail`);
}

export function amendHistoricalClaim(id: string, statement: string, episode?: DecisionEpisode) {
  return apiClient.post<MemoryClaim>(`${ROOT}/claims/mine/${id}/correct`, {
    statement,
    episode,
    historical: true,
  });
}
