/**
 * API client for a skill's improvement sessions and the skill's own test questions.
 *
 * A session's steps share the agent session's routes under `/skills/{id}/improvements`
 * (`lib/improvement-subject.ts`); what is only a skill's is here.
 */

import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import type { Dataset } from "@/types/datasets";
import type {
  SkillImprovement,
  SkillImprovementAwaiting,
  SkillImprovementEstimate,
  SkillProblems,
} from "@/types/skill-improvement";

const root = (skillId: string) => `/skills/${skillId}/improvements`;

/** Where a new session starts: its line, and the agent session that handed it over, if any. */
export interface SkillImprovementOrigin {
  forkId: string | null;
  fromRun: string | null;
}

const originBody = ({ forkId, fromRun }: SkillImprovementOrigin) => ({
  fork_id: forkId,
  ...(fromRun === null ? {} : { from_run: fromRun }),
});

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
  origin: SkillImprovementOrigin,
): Promise<SkillImprovementEstimate> {
  return apiClient.post<SkillImprovementEstimate>(`${root(skillId)}/estimate`, originBody(origin));
}

export function startSkillImprovement(
  skillId: string,
  origin: SkillImprovementOrigin,
  budgetUsd: string,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(root(skillId), {
    ...originBody(origin),
    budget_usd: budgetUsd,
  });
}

export function getSkillProblems(skillId: string, sessionId: string): Promise<SkillProblems> {
  return apiClient.get<SkillProblems>(`${root(skillId)}/${sessionId}/evidence`);
}

/** Apply the measured attempt as the line's next version, pinning the agents it made worse. */
export function applySkillImprovement(
  skillId: string,
  sessionId: string,
  body: { acknowledge_unknown: boolean; pin_worse: boolean },
): Promise<{ session: SkillImprovement }> {
  return apiClient.post<{ session: SkillImprovement }>(`${root(skillId)}/${sessionId}/apply`, {
    confirmed: true,
    ...body,
  });
}

/** Make a fork with the measured attempt for the agents it helped. */
export function forkSkillImprovement(
  skillId: string,
  sessionId: string,
  body: { name: string; acknowledge_unknown: boolean },
): Promise<{ session: SkillImprovement }> {
  return apiClient.post<{ session: SkillImprovement }>(`${root(skillId)}/${sessionId}/fork`, {
    confirmed: true,
    ...body,
  });
}

/** Skill sessions anywhere the reader may see that wait for a person. */
export function listSkillImprovementsAwaiting(): Promise<SkillImprovementAwaiting[]> {
  return apiClient.get<SkillImprovementAwaiting[]>("/skill-improvements/awaiting");
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
