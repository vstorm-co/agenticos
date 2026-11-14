"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  AgentTestSetBootstrap,
  AgentTestSetEstimate,
  AgentTestSetRequest,
} from "@/types/agent-test-set";

/**
 * Building an agent's test set from its rated answers, and estimating it first.
 *
 * Neither says anything on its own: the screen that builds it shows the counts,
 * the grader and whether there are too few questions to measure a change.
 */
export function useAgentTestSet(agentId: string) {
  const queryClient = useQueryClient();
  const estimate = useMutation({
    mutationFn: (request: AgentTestSetRequest) =>
      apiClient.post<AgentTestSetEstimate>(`/agents/${agentId}/test-set/estimate`, request),
  });
  const build = useMutation({
    mutationFn: (request: AgentTestSetRequest) =>
      apiClient.post<AgentTestSetBootstrap>(`/agents/${agentId}/test-set`, request),
    // A build may create the test set's judge, which is an agent too.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
        queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
      ]),
  });
  return { estimate, build };
}
