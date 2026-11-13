"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PAGE_SIZE } from "@/components/ui";
import { qk } from "@/lib/query-keys";
import {
  changeSkillBinding,
  createSkillFork,
  getMainLatest,
  createSkillVersion,
  getSkillUsage,
  getSkillVersion,
  listSkillAgents,
  listSkillForks,
  listSkillVersions,
  restoreSkillVersion,
  type BindingCheck,
  type BindingTarget,
  type SkillVersionEdit,
} from "@/lib/skill-versions-api";

/** One page of a line's versions, newest first; `forkId` null is main. */
/**
 * The page of a line's list holding version `number`, when the line's newest is
 * `newest`: versions run newest first, so the page follows from the gap. Never below
 * the first page - a newest read before a version saved since would point above it.
 */
export function versionPage(newest: number, number: number): number {
  return Math.max(0, Math.floor((newest - number) / PAGE_SIZE));
}

export function useSkillVersions(skillId: string, forkId: string | null, page: number) {
  const skip = Math.max(0, page) * PAGE_SIZE;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.skills.versions(skillId, forkId, skip),
    queryFn: () => listSkillVersions(skillId, { forkId, skip, limit: PAGE_SIZE }),
  });
  return { versions: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}

export function useSkillVersion(skillId: string, versionId: string | null) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.skills.version(skillId, versionId ?? ""),
    queryFn: () => getSkillVersion(skillId, versionId!),
    enabled: versionId !== null,
    // A version never changes once saved.
    staleTime: Infinity,
  });
  return { version: data, isLoading, error, refetch };
}

export function useSkillForks(skillId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.skills.forks(skillId),
    queryFn: () => listSkillForks(skillId),
  });
  return { forks: data?.items ?? [], isLoading, error };
}

/** How often the skill was used, by agent, over the last `days` days. */
export function useSkillUsage(skillId: string, days: number) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.skills.usage(skillId, days),
    queryFn: () => getSkillUsage(skillId, days),
  });
  return { usage: data, isLoading, error };
}

export function useSkillAgents(skillId: string) {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: qk.skills.agents(skillId),
    queryFn: () => listSkillAgents(skillId),
  });
  return { agents: data, isLoading, error, retry: refetch, retrying: isFetching };
}

/**
 * Writes to a skill's lines and bindings.
 *
 * Each settles by reading the whole skill again: a new version moves the line's
 * latest, the agents following it, the tree and the list card at once.
 */
export function useSkillVersionWrites(skillId: string) {
  const queryClient = useQueryClient();
  const settle = useCallback(async () => {
    await queryClient.cancelQueries({ queryKey: qk.skills.all() });
    await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
  }, [queryClient]);

  const edit = useMutation({
    mutationFn: (change: SkillVersionEdit) => createSkillVersion(skillId, change),
    onSettled: settle,
  });
  const restore = useMutation({
    mutationFn: ({ versionId, baseVersionId }: { versionId: string; baseVersionId: string }) =>
      restoreSkillVersion(skillId, versionId, baseVersionId),
    onSettled: settle,
  });
  const changeBinding = useMutation({
    mutationFn: ({
      agentId,
      target,
      check = null,
    }: {
      agentId: string;
      target: BindingTarget;
      check?: BindingCheck | null;
    }) => changeSkillBinding(skillId, agentId, target, check),
    onSettled: async () => {
      await settle();
      await queryClient.invalidateQueries({ queryKey: qk.agents.all() });
      await queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) });
    },
  });
  const createFork = useMutation({
    mutationFn: (fork: { name: string; fromVersionId: string }) => createSkillFork(skillId, fork),
    onSettled: settle,
  });
  /** Read main's newest version fresh, so a fork is not started from one superseded meanwhile. */
  const mainLatest = useCallback(() => getMainLatest(skillId), [skillId]);
  return { edit, restore, changeBinding, createFork, mainLatest };
}
