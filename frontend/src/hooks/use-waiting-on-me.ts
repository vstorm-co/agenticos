"use client";

import { suiteState } from "@/components/evals/suites/suite-format";
import { usePermissions } from "@/hooks/use-permissions";
import { useWaitingSuggestions } from "@/hooks/use-authoring";
import { useVisibleEvalSuites } from "@/hooks/use-eval-suites";
import { useReviewQueue } from "@/hooks/use-scoring";
import type { AuthoringWaiting } from "@/types/authoring";
import type { PendingDataset } from "@/types/scoring";
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

/** The answers waiting in the datasets the reader may decide; the queue lists every one they may see. */
function decidable(datasets: PendingDataset[]): number {
  return datasets.reduce(
    (sum, dataset) =>
      dataset.can_edit ? sum + dataset.failed + dataset.unscored + dataset.passed : sum,
    0,
  );
}

/**
 * What waits on the reader besides their own tool calls: answers sent to
 * review, suites failing, and the assistant's suggestions. Each counts only what
 * the reader may act on - an answer to review only in a dataset they may edit -
 * and beside the dashboard's cards it costs no request of its own, since they
 * read the same queries. `settled` says the permissions and every list it read
 * answered, so "nothing waits" is a finding rather than a list that has not
 * arrived, failed, or was never asked for.
 */
export function useWaitingOnMe() {
  const { can, isLoaded } = usePermissions();
  const review = useReviewQueue({ limit: 1, enabled: can(Perm.datasetsView) });
  const suites = useVisibleEvalSuites({ enabled: can(Perm.runsView) });
  const suggestions = useWaitingSuggestions({ enabled: can(Perm.agentsEdit) });
  const reads = [review, suites, suggestions];
  return {
    review: decidable(review.datasets),
    suites: suites.suites.filter((suite) => suiteState(suite) === "failing").length,
    suggestions: suggestionCount(suggestions.waiting),
    settled: isLoaded && reads.every((read) => !read.isLoading && read.error === null),
  };
}
