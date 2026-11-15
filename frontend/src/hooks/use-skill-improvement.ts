"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  applySkillImprovement,
  estimateSkillImprovement,
  estimateSkillRecheck,
  forkSkillImprovement,
  getSkillProblems,
  listSkillImprovements,
  listSkillImprovementsAwaiting,
  recheckSkillImprovement,
  startSkillImprovement,
  type SkillImprovementOrigin,
} from "@/lib/skill-improvement-api";
import type { SkillContinuationEstimate } from "@/types/skill-improvement";

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

/** How many sessions History reads at a time. */
export const HISTORY_PAGE = 20;

/**
 * A line's sessions, newest first, a page at a time, read only for someone who may
 * read runs. A short page is the last one; the list does not say how many there are.
 */
export function useSkillImprovementHistory(
  skillId: string,
  forkId: string | null,
  { enabled = true } = {},
) {
  const query = useInfiniteQuery({
    queryKey: qk.skills.improvementHistory(skillId, forkId),
    queryFn: ({ pageParam }) =>
      listSkillImprovements(skillId, forkId, { skip: pageParam, limit: HISTORY_PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < HISTORY_PAGE ? undefined : pages.length * HISTORY_PAGE,
    enabled,
  });
  return {
    sessions: query.data?.pages.flat() ?? [],
    more: query.hasNextPage,
    loadMore: () => void query.fetchNextPage(),
    loadingMore: query.isFetchingNextPage,
    isLoading: query.isLoading,
    error: query.error,
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

/** Apply a measured attempt, or fork it for the agents the person picks. */
export function useSkillAccept(skillId: string, sessionId: string) {
  const queryClient = useQueryClient();
  // Applying with pins and forking both move agents, which the Builder reads too.
  const settle = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
      queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
    ]);
  };
  const apply = useMutation({
    mutationFn: (body: { acknowledge_unknown: boolean; pin_worse: boolean }) =>
      applySkillImprovement(skillId, sessionId, body),
    onSuccess: settle,
  });
  const fork = useMutation({
    mutationFn: (body: { name: string; agent_ids: string[]; acknowledge_unknown: boolean }) =>
      forkSkillImprovement(skillId, sessionId, body),
    onSuccess: settle,
  });
  return { apply, fork };
}

/** Pricing Check again on a stale result, and starting it at that price. */
export function useSkillRecheck(skillId: string, sessionId: string) {
  const queryClient = useQueryClient();
  const estimate = useMutation({
    mutationFn: (budget: string) => estimateSkillRecheck(skillId, sessionId, budget),
  });
  const recheck = useMutation({
    mutationFn: ({ quote, budget }: { quote: SkillContinuationEstimate; budget: string }) =>
      recheckSkillImprovement(skillId, sessionId, quote, budget),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
  });
  return { estimate, recheck };
}
