/**
 * API client for a skill's versions, its forks and the agents bound to them.
 *
 * Every write names the line latest the person was looking at, so a line that
 * moved in the meantime is refused rather than overwritten.
 */

import { apiClient } from "./api-client";
import type {
  SkillAgentList,
  SkillAgentUsage,
  SkillBindingState,
  SkillFork,
  SkillForkList,
  SkillUsage,
  SkillVersionList,
  SkillVersionRead,
} from "@/types/skill-versions";

export function listSkillVersions(
  skillId: string,
  { forkId, skip, limit }: { forkId: string | null; skip: number; limit: number },
): Promise<SkillVersionList> {
  const query = new URLSearchParams({ skip: String(skip), limit: String(limit) });
  if (forkId !== null) query.set("fork_id", forkId);
  return apiClient.get<SkillVersionList>(`/skills/${skillId}/versions?${query}`);
}

export function getSkillVersion(skillId: string, versionId: string): Promise<SkillVersionRead> {
  return apiClient.get<SkillVersionRead>(`/skills/${skillId}/versions/${versionId}`);
}

export interface SkillVersionEdit {
  forkId: string | null;
  baseVersionId: string;
  description: string;
  content: string;
}

/** A new version on one line, written over the latest the person read. */
export function createSkillVersion(
  skillId: string,
  edit: SkillVersionEdit,
): Promise<SkillVersionRead> {
  return apiClient.post<SkillVersionRead>(`/skills/${skillId}/versions`, {
    fork_id: edit.forkId,
    base_version_id: edit.baseVersionId,
    description: edit.description,
    content: edit.content,
  });
}

/** An earlier version brought back as the newest on its own line. */
export function restoreSkillVersion(
  skillId: string,
  versionId: string,
  baseVersionId: string,
): Promise<SkillVersionRead> {
  return apiClient.post<SkillVersionRead>(`/skills/${skillId}/versions/${versionId}/restore`, {
    base_version_id: baseVersionId,
  });
}

export function listSkillForks(skillId: string): Promise<SkillForkList> {
  return apiClient.get<SkillForkList>(`/skills/${skillId}/forks?archived=false`);
}

/** Start a fork from a main version; it serves that version until it saves one of its own. */
export function createSkillFork(
  skillId: string,
  fork: { name: string; fromVersionId: string },
): Promise<SkillFork> {
  return apiClient.post<SkillFork>(`/skills/${skillId}/forks`, {
    name: fork.name,
    from_version_id: fork.fromVersionId,
  });
}

/** How often each agent used the skill over the last `days` days; needs `runs:view`. */
export function getSkillUsage(skillId: string, days: number): Promise<SkillUsage> {
  return apiClient.get<SkillUsage>(`/skills/${skillId}/usage?days=${days}`);
}

/** Main's newest version as the server has it now: what a fork started now starts from. */
export async function getMainLatest(
  skillId: string,
): Promise<{ id: string | null; number: number }> {
  const skill = await apiClient.get<{ latest_version_id: string | null; version: number }>(
    `/skills/${skillId}`,
  );
  return { id: skill.latest_version_id, number: skill.version };
}

export function listSkillAgents(skillId: string): Promise<SkillAgentList> {
  return apiClient.get<SkillAgentList>(`/skills/${skillId}/agents`);
}

export type BindingTarget =
  | { state: Extract<SkillBindingState, "main"> }
  | { state: Extract<SkillBindingState, "pinned">; version: number }
  | { state: Extract<SkillBindingState, "fork">; fork_id: string };

export interface BindingChange {
  /** False when the change went into the draft only, waiting for a publish. */
  published: boolean;
  agent_version: number | null;
  /** The environments serving the new version. */
  environments: string[];
  usage: SkillAgentUsage;
}

/** Move one agent to another version or line of the skill. */
/** The finished check that measured main's newest version on a pinned agent moving to it. */
export interface BindingCheck {
  check_id: string;
  /** Required when that check could not check the agent. */
  acknowledge_unknown: boolean;
}

export function changeSkillBinding(
  skillId: string,
  agentId: string,
  target: BindingTarget,
  check: BindingCheck | null = null,
): Promise<BindingChange> {
  return apiClient.put<BindingChange>(`/skills/${skillId}/agents/${agentId}/binding`, {
    ...target,
    ...check,
  });
}
