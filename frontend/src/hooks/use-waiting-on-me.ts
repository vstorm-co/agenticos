"use client";

import { suiteState } from "@/components/evals/suites/suite-format";
import { usePermissions } from "@/hooks/use-permissions";
import { useWaitingSuggestions } from "@/hooks/use-authoring";
import { useVisibleEvalSuites } from "@/hooks/use-eval-suites";
import { useReviewQueue } from "@/hooks/use-scoring";
import type { AuthoringWaiting } from "@/types/authoring";
import { Perm } from "@/types/permissions";

/** Every change the assistant suggested and nobody decided, however it is split. */
function suggestionCount(waiting: AuthoringWaiting | null): number {
  if (waiting === null) return 0;
  const onAgents = waiting.agents.reduce(
    (sum, agent) => sum + agent.instructions + agent.tools + (agent.fields ?? 0),
    0,
  );
  return onAgents + waiting.skills + (waiting.contexts ?? 0);
}

/**
 * What waits on the reader besides their own tool calls: answers sent to
 * review, suites whose last result failed, and the assistant's suggestions.
 * Each is read only by whoever holds the permission its list asks, and the
 * dashboard's cards read the same queries, so the greeting costs no request
 * of its own beside them.
 */
export function useWaitingOnMe() {
  const { can } = usePermissions();
  const review = useReviewQueue({ limit: 1, enabled: can(Perm.datasetsView) });
  const { suites } = useVisibleEvalSuites({ enabled: can(Perm.runsView) });
  const { waiting } = useWaitingSuggestions({ enabled: can(Perm.agentsEdit) });
  return {
    review: review.total,
    suites: suites.filter((suite) => suiteState(suite) === "failing").length,
    suggestions: suggestionCount(waiting),
  };
}
