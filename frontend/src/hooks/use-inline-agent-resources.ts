"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ContextFileSummary, SkillSummary } from "@/types/providers";

async function catalog<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  for (;;) {
    const page = await apiClient.get<{ items: T[]; total: number }>(
      `${path}?sort=name&skip=${items.length}&limit=100`,
    );
    if (page.items.length === 0 && items.length < page.total) {
      // i18n-exempt: internal diagnostic; callers render the translated ErrorState.
      throw new Error("The resource catalog changed while loading; retry the request");
    }
    items.push(...page.items);
    if (items.length >= page.total) return items;
  }
}

/** The galleries search and page locally, so they need complete metadata catalogs. */
export function useInlineAgentResources() {
  const skills = useQuery({
    queryKey: [...qk.skills.all(), "workflow-catalog"],
    queryFn: () => catalog<SkillSummary>("/skills"),
  });
  const context = useQuery({
    queryKey: [...qk.context.all(), "workflow-catalog"],
    queryFn: () => catalog<ContextFileSummary>("/context"),
  });
  return {
    skills: skills.data ?? [],
    skillTotal: skills.data?.length ?? 0,
    contextFiles: context.data ?? [],
    contextTotal: context.data?.length ?? 0,
    isLoading: skills.isPending || context.isPending,
    error: skills.error ?? context.error,
    refetch: () => Promise.all([skills.refetch(), context.refetch()]),
  };
}
