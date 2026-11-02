"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  applySkillImprovement,
  createSkillTestSet,
  estimateSkillImprovement,
  forkSkillImprovement,
  getSkillProblems,
  getSkillTestSet,
  listSkillImprovements,
  listSkillImprovementsAwaiting,
  startSkillImprovement,
  type SkillImprovementOrigin,
} from "@/lib/skill-improvement-api";

/** One line's sessions, and starting a new one on it. */
export function useSkillImprovements(skillId: string, origin: SkillImprovementOrigin) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: qk.skills.improvements(skillId, origin.forkId),
    queryFn: () => listSkillImprovements(skillId, origin.forkId),
  });
  const estimate = useMutation({ mutationFn: () => estimateSkillImprovement(skillId, origin) });
  const start = useMutation({
    mutationFn: (budgetUsd: string) => startSkillImprovement(skillId, origin, budgetUsd),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
  });
  return {
    sessions: list.data ?? [],
    isLoading: list.isLoading,
    error: list.error,
    estimate,
    start,
  };
}

/** The problems a session found, each with the agents it occurs in. */
export function useSkillProblems(skillId: string, sessionId: string) {
  const query = useQuery({
    queryKey: qk.skills.problems(skillId, sessionId),
    queryFn: () => getSkillProblems(skillId, sessionId),
  });
  return {
    problems: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** Skill sessions waiting for a person, for "Waiting for you". */
export function useSkillImprovementsAwaiting({ enabled = true } = {}) {
  const query = useQuery({
    queryKey: qk.skills.awaiting(),
    queryFn: listSkillImprovementsAwaiting,
    enabled,
  });
  return {
    sessions: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** The skill's own test questions, and writing them when there are none. */
export function useSkillTestSet(skillId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.skills.testSet(skillId),
    queryFn: () => getSkillTestSet(skillId),
  });
  const create = useMutation({
    mutationFn: () => createSkillTestSet(skillId),
    // A 409 means somebody wrote them meanwhile; either way the read is refreshed.
    onSettled: () => queryClient.invalidateQueries({ queryKey: qk.skills.testSet(skillId) }),
  });
  return { testSet: query.data, isLoading: query.isLoading, error: query.error, create };
}

/** Apply a measured attempt, or fork it for the agents it helped. */
export function useSkillAccept(skillId: string, sessionId: string) {
  const queryClient = useQueryClient();
  const settle = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
    ]);
  };
  const apply = useMutation({
    mutationFn: (body: { acknowledge_unknown: boolean; pin_worse: boolean }) =>
      applySkillImprovement(skillId, sessionId, body),
    onSuccess: settle,
  });
  const fork = useMutation({
    mutationFn: (body: { name: string; acknowledge_unknown: boolean }) =>
      forkSkillImprovement(skillId, sessionId, body),
    onSuccess: settle,
  });
  return { apply, fork };
}
