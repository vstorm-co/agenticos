/**
 * API client for checking a skill change on every agent of its line.
 *
 * A check is read until it finishes; deciding it - applying, pinning the agents it
 * made worse, discarding - goes through the check, never around it.
 */

import type {
  SkillCheck,
  SkillCheckApply,
  SkillCheckEstimate,
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

export function getSkillCheck(skillId: string, checkId: string) {
  return apiClient.get<SkillCheck>(`${root(skillId)}/${checkId}`);
}

export function applySkillCheck(skillId: string, checkId: string, body: SkillCheckApply) {
  return apiClient.post<unknown>(`${root(skillId)}/${checkId}/apply`, body);
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

/** Write the skill's test questions from the answers where its agents loaded it. */
export function createSkillTestSet(skillId: string): Promise<Dataset> {
  return apiClient.post<Dataset>(`/skills/${skillId}/test-set`, { from_evidence: true });
}
