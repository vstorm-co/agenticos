"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { SkillArrangement, SkillSections } from "@/types/providers";
import type { SkillSort } from "./use-skills";

/** Which arrangement to ask for, under the listing's own filters. */
export interface SkillSectionsQuery {
  arrange: SkillArrangement;
  search?: string;
  categories?: string[];
  sort?: SkillSort;
  groupId?: string | null;
  /** False while the page shows the plain grid, which needs no sections. */
  enabled?: boolean;
}

/**
 * The skills the caller may see, arranged into counted sections.
 *
 * Arranged on the server, over the whole filtered library rather than a page of
 * it, so a section's count is what its "show all" will page through. Each
 * section carries its first cards; the rest are read with `useSkills({ section })`.
 */
export function useSkillSections({
  arrange,
  search = "",
  categories,
  sort = "name",
  groupId = null,
  enabled = true,
}: SkillSectionsQuery) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.skills.sections({
      arrange,
      search,
      categories: categories ?? [],
      sort,
      groupId: groupId ?? "",
    }),
    queryFn: () => {
      const params = new URLSearchParams({ arrange, sort });
      if (search) params.set("q", search);
      for (const category of categories ?? []) params.append("category", category);
      if (groupId) params.set("group_id", groupId);
      return apiClient.get<SkillSections>(`/skills/sections?${params}`);
    },
    enabled,
    placeholderData: (previous) => previous,
  });

  return {
    sections: data?.sections ?? [],
    total: data?.total ?? 0,
    categories: data?.categories ?? [],
    isLoading,
    error,
    refetch,
  };
}
