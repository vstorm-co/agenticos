"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ScheduleTemplate, ScheduleTemplateList } from "@/types/schedule-templates";

/**
 * The seeded schedule-template catalog.
 *
 * Cached indefinitely like the portal catalog beside it: the list is curated in
 * the backend and changes when it is redeployed, not while someone is reading it.
 * The New-schedule flow offers these before the blank prompt, so a first schedule
 * is a pick rather than an empty box.
 */
export function useScheduleTemplates() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.scheduleTemplates.catalog(),
    queryFn: () => apiClient.get<ScheduleTemplateList>("/schedule-templates"),
    staleTime: Infinity,
  });
  return { templates: (data?.items ?? []) as ScheduleTemplate[], isLoading, error };
}
