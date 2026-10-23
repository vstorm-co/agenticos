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
 * review, suites failing, and the assistant's suggestions. Each is read only by
 * whoever may act on it - deciding a review takes `datasets:edit` - and beside
 * the dashboard's cards it costs no request of its own, since they read the same
 * queries. `settled` says every list it read answered, so "nothing waits" is a
 * finding rather than a list that has not arrived or failed.
 */
export function useWaitingOnMe() {
  const { can } = usePermissions();
  const review = useReviewQueue({ limit: 1, enabled: can(Perm.datasetsEdit) });
  const suites = useVisibleEvalSuites({ enabled: can(Perm.runsView) });
  const suggestions = useWaitingSuggestions({ enabled: can(Perm.agentsEdit) });
  const reads = [review, suites, suggestions];
  return {
    review: review.total,
    suites: suites.suites.filter((suite) => suiteState(suite) === "failing").length,
    suggestions: suggestionCount(suggestions.waiting),
    settled: reads.every((read) => !read.isLoading && read.error === null),
  };
}
