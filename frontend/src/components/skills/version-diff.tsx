"use client";

import { useTranslations } from "next-intl";

import { DiffView } from "@/components/authoring/diff-view";
import { Skeleton } from "@/components/ui";
import { useSkillVersion } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import type { SkillVersionRead, SkillVersionResource } from "@/types/skill-versions";

/**
 * Which files a version added, removed or changed against the one before it. A file's
 * description is part of the file, so a new description alone is a change.
 */
export function fileChanges(
  before: SkillVersionResource[],
  after: SkillVersionResource[],
): { added: string[]; removed: string[]; changed: string[] } {
  const old = new Map(before.map((file) => [file.name, file]));
  const now = new Map(after.map((file) => [file.name, file]));
  return {
    added: after.filter((file) => !old.has(file.name)).map((file) => file.name),
    removed: before.filter((file) => !now.has(file.name)).map((file) => file.name),
    changed: after
      .filter((file) => {
        const was = old.get(file.name);
        return (
          was !== undefined && (was.digest !== file.digest || was.description !== file.description)
        );
      })
      .map((file) => file.name),
  };
}

/**
 * What one version changed: its description and body against the version it came
 * from - a fork's first version against its base on main - and its files by name.
 */
export function VersionDiff({
  skillId,
  versionId,
  previousId,
}: {
  skillId: string;
  versionId: string;
  previousId: string | null;
}) {
  const t = useTranslations("skills.page.history");
  const tErrors = useTranslations("errors");
  const after = useSkillVersion(skillId, versionId);
  const before = useSkillVersion(skillId, previousId);
  const failed = after.error ?? before.error;
  if (failed) return <p className="text-destructive text-sm">{getErrorMessage(failed, tErrors)}</p>;
  if (after.version === undefined || (previousId !== null && before.version === undefined)) {
    return <Skeleton className="h-24 w-full" aria-label={t("loadingChanges")} />;
  }
  return <Changes before={before.version ?? null} after={after.version} />;
}

function Changes({ before, after }: { before: SkillVersionRead | null; after: SkillVersionRead }) {
  const t = useTranslations("skills.page.history");
  const files = fileChanges(before?.resources ?? [], after.resources);
  const groups = [
    { key: "added", names: files.added },
    { key: "removed", names: files.removed },
    { key: "changed", names: files.changed },
  ] as const;
  return (
    <div className="space-y-3">
      {(before?.description ?? "") !== after.description && (
        <section className="space-y-1">
          <h4 className="text-xs font-medium">{t("description")}</h4>
          <DiffView before={before?.description ?? ""} after={after.description} />
        </section>
      )}
      {(before?.content ?? "") === after.content ? (
        <p className="text-muted-foreground text-xs">{t("bodyUnchanged")}</p>
      ) : (
        <section className="space-y-1">
          <h4 className="text-xs font-medium">{t("body")}</h4>
          <DiffView before={before?.content ?? ""} after={after.content} />
        </section>
      )}
      {groups.some((group) => group.names.length > 0) && (
        <section className="space-y-1">
          <h4 className="text-xs font-medium">{t("files")}</h4>
          <ul className="space-y-0.5 text-xs">
            {groups.flatMap((group) =>
              group.names.map((name) => (
                <li key={`${group.key}:${name}`}>
                  <span className="font-mono">{name}</span>{" "}
                  <span className="text-muted-foreground">{t(`file.${group.key}`)}</span>
                </li>
              )),
            )}
          </ul>
        </section>
      )}
    </div>
  );
}
