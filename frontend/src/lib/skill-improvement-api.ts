/**
 * API client for a skill's improvement sessions.
 *
 * A session's steps share the agent session's routes under `/skills/{id}/improvements`
 * (`lib/improvement-subject.ts`); what is only a skill's is here.
 */

import { apiClient } from "./api-client";
import type {
  SkillContinuationEstimate,
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

/** The price of checking the result's chosen changes again on the line as it is now. */
export function estimateSkillRecheck(
  skillId: string,
  sessionId: string,
): Promise<SkillContinuationEstimate> {
  return apiClient.post<SkillContinuationEstimate>(
    `${root(skillId)}/${sessionId}/recheck/estimate`,
    {},
  );
}

/** Check the result's chosen changes again, at the quoted price. */
export function recheckSkillImprovement(
  skillId: string,
  sessionId: string,
  quote: SkillContinuationEstimate,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(`${root(skillId)}/${sessionId}/recheck`, {
    confirmed: true,
    budget_usd: quote.budget_usd,
    estimate_usd: quote.total_usd,
    candidate_hash: quote.candidate_hash,
  });
}

/** Skill sessions anywhere the reader may see that wait for a person. */
export function listSkillImprovementsAwaiting(): Promise<SkillImprovementAwaiting[]> {
  return apiClient.get<SkillImprovementAwaiting[]>("/skill-improvements/awaiting");
}
