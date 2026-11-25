"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import {
  getMainLatest,
  getSkillVersion,
  getSkillVersionFile,
  listSkillForks,
} from "@/lib/skill-versions-api";

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

/** One file as a version holds it; idle until all three are known. Versions never change. */
export function useSkillVersionFile(
  skillId: string | null,
  versionId: string | null,
  name: string | null,
) {
  return useQuery({
    queryKey: [...qk.skills.all(), "version-file", skillId, versionId, name],
    enabled: skillId !== null && versionId !== null && name !== null,
    staleTime: Infinity,
    queryFn: () => getSkillVersionFile(skillId!, versionId!, name!),
  });
}
