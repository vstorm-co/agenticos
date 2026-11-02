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
import { apiClient } from "./api-client";

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
