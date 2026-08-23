"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { TriggerTemplate, TriggerTemplateList } from "@/types/trigger-templates";

/**
 * The seeded trigger-template catalog, both modes in one list.
 *
 * Cached indefinitely like the portal catalog beside it: the list is curated in
 * the backend and changes when it is redeployed, not while someone is reading it.
 * The create flows offer these before the blank prompt - schedule templates on
 * the New-schedule flow, each source's event templates on that source's message
 * step - so a first trigger is a pick rather than an empty box.
 */
export function useTriggerTemplates() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.triggerTemplates.catalog(),
    queryFn: () => apiClient.get<TriggerTemplateList>("/trigger-templates"),
    staleTime: Infinity,
  });
  return { templates: (data?.items ?? []) as TriggerTemplate[], isLoading, error };
}
