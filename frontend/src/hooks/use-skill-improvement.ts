"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  acceptSkillImprovement,
  createSkillTestSet,
  estimateSkillImprovement,
  getSkillCheck,
  getSkillTestSet,
  listSkillImprovements,
  startSkillImprovement,
} from "@/lib/skill-improvement-api";
import type { SkillAccept } from "@/types/skill-improvement";

/** A live check is also refreshed by its session's change event; this covers a closed socket. */
const CHECK_FALLBACK_MS = 30_000;

/** One line's sessions, and starting a new one on it. */
export function useSkillImprovements(skillId: string, forkId: string | null) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: qk.skills.improvements(skillId, forkId),
    queryFn: () => listSkillImprovements(skillId, forkId),
  });
  const estimate = useMutation({ mutationFn: () => estimateSkillImprovement(skillId, forkId) });
  const start = useMutation({
    mutationFn: (budgetUsd: string) => startSkillImprovement(skillId, forkId, budgetUsd),
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

/** The check that measured an attempt, read while it still runs. */
export function useSkillCheck(skillId: string, checkId: string | null) {
  const query = useQuery({
    queryKey: qk.skills.check(skillId, checkId ?? ""),
    queryFn: () => getSkillCheck(skillId, checkId!),
    enabled: checkId !== null,
    refetchInterval: (current) =>
      current.state.data && current.state.data.verdict === null ? CHECK_FALLBACK_MS : false,
  });
  return { check: query.data, isLoading: query.isLoading, error: query.error };
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
  return useMutation({
    mutationFn: (accept: SkillAccept) => acceptSkillImprovement(skillId, sessionId, accept),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
        queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
      ]);
    },
  });
}
