"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getMainLatest, getSkillVersion, listSkillForks } from "@/lib/skill-versions-api";

/** Resolve the line being reviewed, then read immutable files from that version. */
export function useSkillProposalBaseline(skillId: string | null, forkId: string | null) {
  const t = useTranslations("skills.reviewUpdates");
  return useQuery({
    queryKey: [...qk.skills.all(), "proposal-baseline", skillId, forkId],
    enabled: skillId !== null,
    queryFn: async () => {
      if (skillId === null) throw new Error(t("compareFailed"));
      const latest =
        forkId === null
          ? await getMainLatest(skillId)
          : await listSkillForks(skillId).then(({ items }) => {
              const fork = items.find((item) => item.id === forkId);
              if (!fork) throw new Error(t("compareFailed"));
              return fork.latest ?? fork.base;
            });
      if (latest.id === null) throw new Error(t("compareFailed"));
      return getSkillVersion(skillId, latest.id);
    },
  });
}

export function useSkillProposalFile(
  skillId: string | null,
  versionId: string | null,
  name: string | null,
) {
  return useQuery({
    queryKey: [...qk.skills.all(), "proposal-file", skillId, versionId, name],
    enabled: skillId !== null && versionId !== null && name !== null,
    staleTime: Infinity,
    queryFn: () =>
      apiClient.get<{ content: string }>(
        `/skills/${skillId}/versions/${versionId}/resources/${name!.split("/").map(encodeURIComponent).join("/")}`,
      ),
  });
}
