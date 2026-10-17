"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { MentionableList } from "@/types/mention";

/**
 * What the person may point this agent at with `@` - its servers, the agents it
 * hands work to, its capabilities, skills and knowledge.
 *
 * Read as soon as the agent is chosen rather than when `@` is typed, so the menu
 * opens on a list already in hand. `draft` reads the Builder's draft, which is
 * what its test panel runs. Not retried: a refusal is an answer the menu
 * shows, and three retries with backoff kept it saying "loading" for seconds.
 */
export function useMentionables(agentId: string | null, draft = false) {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.agents.mentionables(agentId ?? "", draft),
    queryFn: () =>
      apiClient.get<MentionableList>(`/agents/${agentId}/mentionables`, {
        params: draft ? { draft: "true" } : undefined,
      }),
    enabled: agentId !== null,
    staleTime: 60_000,
    retry: false,
  });
  return { items: data?.items ?? [], isLoading, isError };
}
