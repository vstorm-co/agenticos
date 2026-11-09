/**
 * API client for checking a skill change on every agent of its line.
 *
 * A check is read until it finishes; deciding it - applying, pinning the agents it
 * made worse, discarding - goes through the check, never around it.
 */

import type {
  SkillCheck,
  SkillCheckApply,
  SkillCheckAwaiting,
  SkillCheckEstimate,
  SkillCheckFork,
  SkillCheckStart,
} from "@/types/skill-checks";
import type { Dataset } from "@/types/datasets";
import { apiClient } from "./api-client";
import { ApiError } from "./api-error";

const root = (skillId: string) => `/skills/${skillId}/checks`;

export function estimateSkillCheck(skillId: string, body: SkillCheckStart) {
  return apiClient.post<SkillCheckEstimate>(`${root(skillId)}/estimate`, body);
}

export function startSkillCheck(skillId: string, body: SkillCheckStart) {
  return apiClient.post<SkillCheck>(root(skillId), body);
}

const update = (skillId: string, agentId: string) =>
  `/skills/${skillId}/agents/${agentId}/update-check`;

/** What checking main's newest version on one pinned agent would run and cost. */
export function estimateUpdateCheck(skillId: string, agentId: string) {
  return apiClient.post<SkillCheckEstimate>(`${update(skillId, agentId)}/estimate`, {});
}

/** Check main's newest version on one pinned agent, accepted by moving that agent. */
export function startUpdateCheck(skillId: string, agentId: string) {
  return apiClient.post<SkillCheck>(update(skillId, agentId), {});
}

/**
 * A line's newest checks, newest first; main's when `forkId` is null. Twenty, so the
 * checks sessions started rarely push an open one of a person's own off the page.
 */
export function listSkillChecks(skillId: string, forkId: string | null) {
  const query = new URLSearchParams({ limit: "20" });
  if (forkId !== null) query.set("fork_id", forkId);
  return apiClient.get<{ items: SkillCheck[]; total: number }>(`${root(skillId)}?${query}`);
}

/** The checks a person started that still run or wait for a decision, on skills the reader may edit. */
export function listSkillChecksAwaiting() {
  return apiClient.get<SkillCheckAwaiting[]>("/skill-checks/awaiting");
}

export function getSkillCheck(skillId: string, checkId: string) {
  return apiClient.get<SkillCheck>(`${root(skillId)}/${checkId}`);
}

export function cancelSkillCheck(skillId: string, checkId: string) {
  return apiClient.post<SkillCheck>(`${root(skillId)}/${checkId}/cancel`, {});
}

export function applySkillCheck(skillId: string, checkId: string, body: SkillCheckApply) {
  return apiClient.post<unknown>(`${root(skillId)}/${checkId}/apply`, body);
}

/** Make the checked text a fork for the agents picked; main stays as it is. */
export function forkSkillCheck(skillId: string, checkId: string, body: SkillCheckFork) {
  return apiClient.post<unknown>(`${root(skillId)}/${checkId}/fork`, body);
}

export function discardSkillCheck(skillId: string, checkId: string) {
  return apiClient.post<SkillCheck>(`${root(skillId)}/${checkId}/discard`, {});
}

/** The skill's own test questions, which let an agent without its own be checked; null while it has none. */
export async function getSkillTestSet(skillId: string): Promise<Dataset | null> {
  try {
    return await apiClient.get<Dataset>(`/skills/${skillId}/test-set`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * Give the skill its test questions: from the answers where its agents loaded it, or
 * an empty set to fill in by hand.
 */
export function createSkillTestSet(skillId: string, fromEvidence = true): Promise<Dataset> {
  return apiClient.post<Dataset>(`/skills/${skillId}/test-set`, { from_evidence: fromEvidence });
}
