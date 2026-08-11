"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { TriggerList } from "@/types/triggers";

/**
 * Every schedule and event trigger across the organization, for the surfaces that
 * list them away from any one agent - the chat sidebar section and the Activity
 * "Scheduled" tab. The server filters to the agents the caller may run and names
 * each row with its agent, so this is read-only; the writes live in `useTriggers`,
 * whose invalidation reaches this query through the shared `qk.triggers.all()`
 * prefix.
 *
 * `enabled` lets a caller hold the request until it is wanted - the sidebar does
 * not fetch the list until its section is expanded.
 */
export function useOrgTriggers(enabled = true) {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.triggers.orgList(),
    queryFn: () => apiClient.get<TriggerList>("/triggers"),
    enabled,
  });

  return {
    triggers: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError,
  };
}
