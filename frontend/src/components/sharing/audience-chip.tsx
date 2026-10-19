"use client";

import { Building2, Lock, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * Who a resource is for, on its card (#2072): everyone, its departments by name,
 * or nobody beyond whoever it was shared with.
 *
 * Everyone *and* its departments when it is both: a group is also how a list is
 * grouped (#2124), so a skill the whole company may read but that belongs to
 * Sales says so - "Everyone" alone hid the department it was filed under.
 */
export function AudienceChip({
  visibility,
  groups = [],
  className,
}: {
  visibility: string;
  groups?: string[];
  className?: string;
}) {
  const t = useTranslations("audience");
  const everyone = visibility === "org";
  return (
    <span
      className={cn("text-muted-foreground flex min-w-0 items-center gap-1 text-xs", className)}
    >
      {everyone ? (
        <Building2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : groups.length === 0 ? (
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : null}
      {everyone ? (
        <span className="shrink-0">{t("everyone")}</span>
      ) : groups.length === 0 ? (
        <span className="truncate">{t("chipPrivate")}</span>
      ) : null}
      {everyone && groups.length > 0 && (
        <span className="shrink-0" aria-hidden>
          ·
        </span>
      )}
      {groups.length > 0 && (
        <>
          <Users className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{groupsLabel(groups, t)}</span>
        </>
      )}
    </span>
  );
}

/**
 * The departments a resource is shared with, and nothing when it is shared with none.
 *
 * For a picker's row (#2124), where "Everyone" on every other line would be noise
 * and the department is what tells two similar skills apart.
 */
export function GroupsChip({ groups }: { groups: string[] | undefined }) {
  const t = useTranslations("audience");
  if (groups === undefined || groups.length === 0) return null;
  return (
    <span className="text-muted-foreground inline-flex min-w-0 items-center gap-1 text-xs">
      <Users className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="truncate">{groupsLabel(groups, t)}</span>
    </span>
  );
}

/** Two group names, then how many more - a card has room for a department, not a list. */
export function groupsLabel(
  groups: string[],
  t: (key: string, values: Record<string, string | number>) => string,
): string {
  const shown = groups.slice(0, 2).join(", ");
  const more = groups.length - 2;
  return more > 0 ? t("chipGroupsMore", { names: shown, count: more }) : shown;
}
