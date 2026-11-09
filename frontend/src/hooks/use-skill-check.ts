"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  applySkillCheck,
  cancelSkillCheck,
  createSkillTestSet,
  discardSkillCheck,
  estimateSkillCheck,
  forkSkillCheck,
  getSkillCheck,
  getSkillTestSet,
  listSkillChecks,
  listSkillChecksAwaiting,
  startSkillCheck,
} from "@/lib/skill-checks-api";
import type {
  SkillCheck,
  SkillCheckApply,
  SkillCheckFork,
  SkillCheckStart,
} from "@/types/skill-checks";

/** How often a running check is read again: its stages are eval runs, minutes long. */
export const SKILL_CHECK_POLL_MS = 5000;

/**
 * A check is decided by whoever gets there first, in another tab or by another
 * reviewer, so it is read again each time it is shown and each time the window
 * comes back, rather than served from a cache that may offer what is gone.
 */
const ALWAYS_FRESH = {
  staleTime: 0,
  refetchOnMount: "always",
  refetchOnWindowFocus: true,
} as const;

/**
 * One skill change's check: estimate and start it, read it until it finishes,
 * then apply, fork or discard it. Deciding changes the skill and the waiting
 * changes, so both are read again afterwards; a refused decision reads the check
 * and the skill again, since it is usually refused for being out of date.
 */
export function useSkillCheck(skillId: string, checkId: string | null) {
  const queryClient = useQueryClient();
  const key = qk.skillChecks.detail(skillId, checkId ?? "");
  const check = useQuery({
    queryKey: key,
    queryFn: () => getSkillCheck(skillId, checkId as string),
    enabled: checkId !== null,
    ...ALWAYS_FRESH,
    refetchInterval: (current) =>
      current.state.data?.status === "running" ? SKILL_CHECK_POLL_MS : false,
  });
  const decided = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.skillChanges.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) }),
      queryClient.invalidateQueries({ queryKey: qk.skillChecks.awaiting() }),
      // Applying with pins and forking for the helped agents move agents.
      queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
    ]);
  };
  const refused = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) }),
      queryClient.invalidateQueries({ queryKey: qk.skillChecks.awaiting() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.detail(skillId) }),
    ]);
  };
  return {
    check: check.data ?? null,
    estimate: useMutation({
      mutationFn: (body: SkillCheckStart) => estimateSkillCheck(skillId, body),
    }),
    start: useMutation({
      mutationFn: (body: SkillCheckStart) => startSkillCheck(skillId, body),
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) }),
          queryClient.invalidateQueries({ queryKey: qk.skillChecks.awaiting() }),
        ]),
    }),
    apply: useMutation({
      mutationFn: (body: SkillCheckApply) => applySkillCheck(skillId, checkId as string, body),
      onSuccess: decided,
      onError: refused,
    }),
    fork: useMutation({
      mutationFn: (body: SkillCheckFork) => forkSkillCheck(skillId, checkId as string, body),
      onSuccess: decided,
      onError: refused,
    }),
    discard: useMutation({
      mutationFn: () => discardSkillCheck(skillId, checkId as string),
      onSuccess: decided,
      onError: refused,
    }),
    cancel: useMutation({
      mutationFn: () => cancelSkillCheck(skillId, checkId as string),
      onSuccess: decided,
    }),
  };
}

/**
 * The line's newest check a person still has to come back to: one running, or one
 * finished and not yet decided. A check a session started is decided in the session,
 * and a pinned agent's catch-up by moving that agent, so both are left out. Read
 * again while it runs.
 */
export function useOpenSkillCheck(skillId: string, forkId: string | null): SkillCheck | null {
  const { data } = useLineChecks(skillId, forkId);
  return (
    data?.items.find(
      (check) =>
        !check.session_id &&
        check.source !== "catch_up" &&
        (check.status === "running" || check.status === "done"),
    ) ?? null
  );
}

/**
 * The checks a person started, on any skill the reader may edit, that still run or
 * wait for a decision. Read again while one runs.
 */
export function useSkillChecksAwaiting({ enabled = true }: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: qk.skillChecks.awaiting(),
    queryFn: listSkillChecksAwaiting,
    enabled,
    ...ALWAYS_FRESH,
    refetchInterval: (current) =>
      current.state.data?.some((check) => check.status === "running") ? SKILL_CHECK_POLL_MS : false,
  });
  return {
    checks: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** A line's newest checks, read again while one of them runs. */
function useLineChecks(skillId: string, forkId: string | null) {
  return useQuery({
    queryKey: qk.skillChecks.line(skillId, forkId),
    queryFn: () => listSkillChecks(skillId, forkId),
    ...ALWAYS_FRESH,
    refetchInterval: (current) =>
      current.state.data?.items.some((check) => check.status === "running")
        ? SKILL_CHECK_POLL_MS
        : false,
  });
}

/** A line's checks, newest first: what each found and what was done with it. */
export function useSkillCheckHistory(skillId: string, forkId: string | null) {
  const { data, isLoading, error } = useLineChecks(skillId, forkId);
  return { checks: data?.items, total: data?.total ?? 0, isLoading, error };
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
