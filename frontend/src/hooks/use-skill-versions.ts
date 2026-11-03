"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PAGE_SIZE } from "@/components/ui";
import { qk } from "@/lib/query-keys";
import {
  changeSkillBinding,
  createSkillFork,
  createSkillVersion,
  getSkillVersion,
  listSkillAgents,
  listSkillForks,
  listSkillVersions,
  restoreSkillVersion,
  type BindingTarget,
  type SkillVersionEdit,
} from "@/lib/skill-versions-api";

/** One page of a line's versions, newest first; `forkId` null is main. */
export function useSkillVersions(skillId: string, forkId: string | null, page: number) {
  const skip = page * PAGE_SIZE;
  const { data, isLoading, error } = useQuery({
    queryKey: qk.skills.versions(skillId, forkId, skip),
    queryFn: () => listSkillVersions(skillId, { forkId, skip, limit: PAGE_SIZE }),
  });
  return { versions: data?.items ?? [], total: data?.total ?? 0, isLoading, error };
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

export function useSkillAgents(skillId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.skills.agents(skillId),
    queryFn: () => listSkillAgents(skillId),
  });
  return { agents: data, isLoading, error };
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
    mutationFn: ({ agentId, target }: { agentId: string; target: BindingTarget }) =>
      changeSkillBinding(skillId, agentId, target),
    onSettled: async () => {
      await settle();
      await queryClient.invalidateQueries({ queryKey: qk.agents.all() });
    },
  });
  const createFork = useMutation({
    mutationFn: (fork: { name: string; fromVersionId: string }) => createSkillFork(skillId, fork),
    onSettled: settle,
  });
  return { edit, restore, changeBinding, createFork };
}
