"use client";

import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { ListCard, Skeleton } from "@/components/ui";
import { useSkillVersion } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { VersionSections } from "./version-sections";

/**
 * What the line shown serves now - its description, instructions and files - read
 * the way the comparison reads a version, with nothing to compare it against.
 */
export function SkillContent({
  skillId,
  versionId,
  label,
}: {
  skillId: string;
  /** The version the line serves: main's newest, or the fork's (its base until it has one). */
  versionId: string | null;
  /** That version as the page names it: "v3", "Prints v1". */
  label: string;
}) {
  const t = useTranslations("skills.page.content");
  const tErrors = useTranslations("errors");
  const { version, error } = useSkillVersion(skillId, versionId);
  return (
    <ListCard title={t("title")} counted={label} headerTour="skill-content">
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : version === undefined ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="space-y-3">
          <VersionSections key={version.id} version={version} />
        </div>
      )}
    </ListCard>
  );
}
