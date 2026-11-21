"use client";

import { usePermissions } from "@/hooks/use-permissions";
import { useSuggestions } from "@/hooks/use-suggestions";
import { useWaitingChatQuestions } from "@/hooks/use-waiting-chat-questions";
import { Perm } from "@/types/permissions";

export type WaitingKind = "approvals" | "questions" | "suggestions";

/** What is personally waiting on the reader, rather than the organization's queues. */
export function waitingOn(
  approvals: number,
  others: { questions: number; suggestions: number },
): [WaitingKind, number][] {
  return (
    [
      ["approvals", approvals],
      ["questions", others.questions],
      ["suggestions", others.suggestions],
    ] satisfies [WaitingKind, number][]
  ).filter(([, count]) => count > 0);
}

/** Shares the Briefing query; authoring queues and evaluation health belong to other views. */
export function useWaitingOnMe() {
  const { can, isLoaded } = usePermissions();
  const enabled = can(Perm.agentsRun);
  const proposals = useSuggestions(enabled);
  const questions = useWaitingChatQuestions();
  return {
    questions: questions.count,
    suggestions: enabled ? proposals.suggestions.length : 0,
    settled:
      isLoaded &&
      (!enabled || (!proposals.isLoading && proposals.error === null)) &&
      !questions.isLoading &&
      questions.error === null,
    failed: (enabled && proposals.error !== null) || questions.error !== null,
    retry: () => {
      if (enabled && proposals.error !== null) void proposals.refetch();
      if (questions.error !== null) void questions.refetch();
    },
  };
}
