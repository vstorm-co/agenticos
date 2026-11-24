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
  SkillImprovementForked,
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

/** One line's sessions: a fork's, or with `forkId` null main's alone - never every line's. */
export function listSkillImprovements(
  skillId: string,
  forkId: string | null,
  page: { skip: number; limit: number } | null = null,
): Promise<SkillImprovement[]> {
  const line: Record<string, string> = forkId === null ? { main: "true" } : { fork_id: forkId };
  return apiClient.get<SkillImprovement[]>(root(skillId), {
    params: page === null ? line : { ...line, skip: String(page.skip), limit: String(page.limit) },
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

/** Make a fork with the measured attempt, and move the agents named onto it - none for []. */
export function forkSkillImprovement(
  skillId: string,
  sessionId: string,
  body: { name: string; agent_ids: string[]; acknowledge_unknown: boolean },
): Promise<SkillImprovementForked> {
  return apiClient.post<SkillImprovementForked>(`${root(skillId)}/${sessionId}/fork`, {
    confirmed: true,
    ...body,
  });
}

/**
 * The price of checking the result's chosen changes again on the line as it is now,
 * and whether `budget` - the session's limit, or a higher one - covers it.
 */
export function estimateSkillRecheck(
  skillId: string,
  sessionId: string,
  budget: string,
): Promise<SkillContinuationEstimate> {
  return apiClient.post<SkillContinuationEstimate>(
    `${root(skillId)}/${sessionId}/recheck/estimate`,
    { budget_usd: budget },
  );
}

/**
 * Check the result's chosen changes again, at the quoted price, within `budget` - the
 * session's limit, or a higher one the person set for this check.
 */
export function recheckSkillImprovement(
  skillId: string,
  sessionId: string,
  quote: SkillContinuationEstimate,
  budget: string,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(`${root(skillId)}/${sessionId}/recheck`, {
    confirmed: true,
    budget_usd: budget,
    estimate_usd: quote.total_usd,
    candidate_hash: quote.candidate_hash,
  });
}

/** Skill sessions anywhere the reader may see that wait for a person. */
export function listSkillImprovementsAwaiting(): Promise<SkillImprovementAwaiting[]> {
  return apiClient.get<SkillImprovementAwaiting[]>("/skill-improvements/awaiting");
}
