"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  applySkillCheck,
  cancelSkillCheck,
  createSkillTestSet,
  discardSkillCheck,
  estimateSkillCheck,
  getSkillCheck,
  getSkillTestSet,
  listSkillChecks,
  startSkillCheck,
} from "@/lib/skill-checks-api";
import type { SkillCheck, SkillCheckApply, SkillCheckStart } from "@/types/skill-checks";

/** How often a running check is read again: its stages are eval runs, minutes long. */
export const SKILL_CHECK_POLL_MS = 5000;

/**
 * One skill change's check: estimate and start it, read it until it finishes,
 * then apply or discard it. Deciding changes the skill and the waiting changes,
 * so both are read again afterwards.
 */
export function useSkillCheck(skillId: string, checkId: string | null) {
  const queryClient = useQueryClient();
  const key = qk.skillChecks.detail(skillId, checkId ?? "");
  const check = useQuery({
    queryKey: key,
    queryFn: () => getSkillCheck(skillId, checkId as string),
    enabled: checkId !== null,
    refetchInterval: (current) =>
      current.state.data?.status === "running" ? SKILL_CHECK_POLL_MS : false,
  });
  const decided = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.skillChanges.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) }),
    ]);
  };
  return {
    check: check.data ?? null,
    estimate: useMutation({
      mutationFn: (body: SkillCheckStart) => estimateSkillCheck(skillId, body),
    }),
    start: useMutation({
      mutationFn: (body: SkillCheckStart) => startSkillCheck(skillId, body),
      onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.skillChecks.skill(skillId) }),
    }),
    apply: useMutation({
      mutationFn: (body: SkillCheckApply) => applySkillCheck(skillId, checkId as string, body),
      onSuccess: decided,
    }),
    discard: useMutation({
      mutationFn: () => discardSkillCheck(skillId, checkId as string),
      onSuccess: decided,
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
 * which says so itself, so it is left out. Read again while it runs.
 */
export function useOpenSkillCheck(skillId: string, forkId: string | null): SkillCheck | null {
  const { data } = useQuery({
    queryKey: qk.skillChecks.line(skillId, forkId),
    queryFn: () => listSkillChecks(skillId, forkId),
    refetchInterval: (current) =>
      current.state.data?.items.some((check) => check.status === "running")
        ? SKILL_CHECK_POLL_MS
        : false,
  });
  return (
    data?.items.find(
      (check) => !check.session_id && (check.status === "running" || check.status === "done"),
    ) ?? null
  );
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
