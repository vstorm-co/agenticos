/**
 * API client for catching a fork up with main and moving a fork to main: the
 * session that merges them, the merge Changes edits, and who main has left behind.
 */

import { apiClient } from "./api-client";
import type { SkillImprovement } from "@/types/skill-improvement";
import type {
  BehindMainList,
  MergeKind,
  ReturnedToMain,
  SkillMerge,
  SkillMergeEstimate,
} from "@/types/skill-merge";

const PATHS: Record<MergeKind, string> = { catch_up: "catch-up", to_main: "to-main" };

const forkRoot = (skillId: string, forkId: string, kind: MergeKind) =>
  `/skills/${skillId}/forks/${forkId}/${PATHS[kind]}`;

const mergeRoot = (skillId: string, sessionId: string) =>
  `/skills/${skillId}/improvements/${sessionId}/merge`;

export function estimateSkillMerge(
  skillId: string,
  forkId: string,
  kind: MergeKind,
): Promise<SkillMergeEstimate> {
  return apiClient.post<SkillMergeEstimate>(`${forkRoot(skillId, forkId, kind)}/estimate`, {});
}

export function startSkillMerge(
  skillId: string,
  forkId: string,
  kind: MergeKind,
  budgetUsd: string,
): Promise<SkillImprovement> {
  return apiClient.post<SkillImprovement>(forkRoot(skillId, forkId, kind), {
    budget_usd: budgetUsd,
  });
}

export function getSkillMerge(skillId: string, sessionId: string): Promise<SkillMerge> {
  return apiClient.get<SkillMerge>(mergeRoot(skillId, sessionId));
}

export function editMergeDescription(
  skillId: string,
  sessionId: string,
  result: string,
): Promise<SkillMerge> {
  return apiClient.patch<SkillMerge>(`${mergeRoot(skillId, sessionId)}/description`, { result });
}

export function editMergePart(
  skillId: string,
  sessionId: string,
  index: number,
  result: string,
): Promise<SkillMerge> {
  return apiClient.patch<SkillMerge>(`${mergeRoot(skillId, sessionId)}/parts/${index}`, {
    result,
  });
}

export function pickMergeFile(
  skillId: string,
  sessionId: string,
  name: string,
  take: "fork" | "main",
): Promise<SkillMerge> {
  return apiClient.patch<SkillMerge>(`${mergeRoot(skillId, sessionId)}/files`, { name, take });
}

/**
 * Move a catch-up's fork agents back to main; the session is accepted with it. Agents main
 * alone could not be checked on go only with `acknowledgeUnknown`.
 */
export function returnSkillImprovementToMain(
  skillId: string,
  sessionId: string,
  acknowledgeUnknown: boolean,
): Promise<{ session: SkillImprovement; returned: ReturnedToMain }> {
  return apiClient.post<{ session: SkillImprovement; returned: ReturnedToMain }>(
    `/skills/${skillId}/improvements/${sessionId}/return-to-main`,
    { confirmed: true, acknowledge_unknown: acknowledgeUnknown },
  );
}

/** Move a fork's agents back to main's newest version; the fork is archived once nobody reads it. */
export function returnForkToMain(skillId: string, forkId: string): Promise<ReturnedToMain> {
  return apiClient.post<ReturnedToMain>(`/skills/${skillId}/forks/${forkId}/return-to-main`, {});
}

/** The pinned agents and forks main has moved past, across the organization. */
export function listBehindMain(): Promise<BehindMainList> {
  return apiClient.get<BehindMainList>("/skills/behind-main");
}
