"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { Trigger, TriggerList } from "@/types/triggers";

/** The server's ceiling for one page; anything larger is clamped to it. */
const PAGE_SIZE = 100;

/**
 * Every page of the org-wide list, gathered into one. The endpoint caps a page
 * at the server limit, so a deployment with more than that many triggers would
 * otherwise silently drop the tail - the older rows a listing with no next-page
 * control can never reach. Walks until it has collected `total`, or a short page
 * says there is no more.
 */
async function fetchAllOrgTriggers(): Promise<TriggerList> {
  const items: Trigger[] = [];
  let skip = 0;
  for (;;) {
    const page = await apiClient.get<TriggerList>(`/triggers?skip=${skip}&limit=${PAGE_SIZE}`);
    items.push(...page.items);
    if (page.items.length < PAGE_SIZE || items.length >= page.total) {
      return { items, total: page.total };
    }
    skip += PAGE_SIZE;
  }
}

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
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.triggers.orgList(),
    queryFn: fetchAllOrgTriggers,
    enabled,
  });

  return {
    triggers: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError,
    error,
    refetch,
  };
}
