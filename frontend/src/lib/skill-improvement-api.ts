/**
 * API client for a skill's improvement sessions, the checks behind them, and the
 * skill's own test questions.
 *
 * A session's steps share the agent session's routes under `/skills/{id}/improvements`
 * (`lib/improvement-subject.ts`); what is only a skill's is here.
 */

import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import type { Dataset } from "@/types/datasets";
import type { SkillCheck } from "@/types/skill-checks";
import type {
  SkillAccept,
  SkillImprovement,
  SkillImprovementEstimate,
} from "@/types/skill-improvement";

const root = (skillId: string) => `/skills/${skillId}/improvements`;

export function listSkillImprovements(
  skillId: string,
  forkId: string | null,
): Promise<SkillImprovement[]> {
  return apiClient.get<SkillImprovement[]>(root(skillId), {
    params: forkId === null ? {} : { fork_id: forkId },
  });
}

export function estimateSkillImprovement(
  skillId: string,
  forkId: string | null,
): Promise<SkillImprovementEstimate> {
  return apiClient.post<SkillImprovementEstimate>(`${root(skillId)}/estimate`, {
    fork_id: forkId,
  });
}

export function startSkillImprovement(
  skillId: string,
  forkId: string | null,
  budgetUsd: string,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(root(skillId), {
    fork_id: forkId,
    budget_usd: budgetUsd,
  });
}

/** Apply the measured attempt, pinning the agents it made worse, or fork it for the ones it helped. */
export function acceptSkillImprovement(
  skillId: string,
  sessionId: string,
  accept: SkillAccept,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(`${root(skillId)}/${sessionId}/accept`, accept);
}

export function getSkillCheck(skillId: string, checkId: string): Promise<SkillCheck> {
  return apiClient.get<SkillCheck>(`/skills/${skillId}/checks/${checkId}`);
}

/** The skill's own test questions, or null while it has none. */
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
