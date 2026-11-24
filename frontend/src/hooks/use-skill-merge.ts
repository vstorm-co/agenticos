"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  editMergeDescription,
  editMergePart,
  estimateSkillMerge,
  getSkillMerge,
  listBehindMain,
  pickMergeFile,
  returnForkToMain,
  returnSkillImprovementToMain,
  startSkillMerge,
} from "@/lib/skill-merge-api";
import type { MergeKind, SkillMerge } from "@/types/skill-merge";

/** Pricing a catch-up or a move to main for one fork, and starting it. */
export function useSkillMergeStart(skillId: string, forkId: string, kind: MergeKind) {
  const queryClient = useQueryClient();
  const estimate = useMutation({ mutationFn: () => estimateSkillMerge(skillId, forkId, kind) });
  const start = useMutation({
    mutationFn: (budgetUsd: string) => startSkillMerge(skillId, forkId, kind, budgetUsd),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
  });
  return { estimate, start };
}

/**
 * A session's merge, and the edits a person makes to it at Changes. `at` is where the
 * session stands - its status and stage - so the merge is read again once it moves on.
 */
export function useSkillMerge(
  skillId: string,
  sessionId: string,
  { at, enabled = true }: { at: string; enabled?: boolean },
) {
  const queryClient = useQueryClient();
  const key = qk.skills.merge(skillId, sessionId, at);
  const query = useQuery({
    queryKey: key,
    queryFn: () => getSkillMerge(skillId, sessionId),
    enabled,
  });
  // The session's Next step is priced on the merge, so it is read again with it.
  const settle = async (merge: SkillMerge) => {
    queryClient.setQueryData(key, merge);
    await queryClient.invalidateQueries({ queryKey: qk.improvements.all() });
  };
  const editDescription = useMutation({
    mutationFn: (result: string) => editMergeDescription(skillId, sessionId, result),
    onSuccess: settle,
  });
  const editPart = useMutation({
    mutationFn: ({ index, result }: { index: number; result: string }) =>
      editMergePart(skillId, sessionId, index, result),
    onSuccess: settle,
  });
  const pickFile = useMutation({
    mutationFn: ({ name, take }: { name: string; take: "fork" | "main" }) =>
      pickMergeFile(skillId, sessionId, name, take),
    onSuccess: settle,
  });
  return {
    merge: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    editDescription,
    editPart,
    pickFile,
  };
}

/** Return a catch-up's fork agents to main, which accepts the session. */
export function useReturnToMain(skillId: string, sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (acknowledgeUnknown: boolean) =>
      returnSkillImprovementToMain(skillId, sessionId, acknowledgeUnknown),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.improvements.all() }),
        queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
      ]),
  });
}

/** Return a fork's agents to main from the skill page, outside any session. */
export function useReturnForkToMain(skillId: string, forkId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => returnForkToMain(skillId, forkId),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
        queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
      ]),
  });
}

/** The pinned agents and forks main has moved past, for "Waiting for you". */
export function useBehindMain({ enabled = true } = {}) {
  const query = useQuery({ queryKey: qk.skills.behindMain(), queryFn: listBehindMain, enabled });
  return {
    behind: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
