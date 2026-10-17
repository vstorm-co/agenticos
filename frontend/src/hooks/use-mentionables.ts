"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { MentionableList } from "@/types/mention";

/**
 * What the person may point this agent at with `@` - its servers, delegates and
 * knowledge, and the agents they may run. Read when the menu first opens.
 */
export function useMentionables(agentId: string | null, enabled: boolean) {
  const { data, isLoading } = useQuery({
    queryKey: qk.agents.mentionables(agentId ?? ""),
    queryFn: () => apiClient.get<MentionableList>(`/agents/${agentId}/mentionables`),
    enabled: enabled && agentId !== null,
    staleTime: 60_000,
  });
  return { items: data?.items ?? [], isLoading };
}
