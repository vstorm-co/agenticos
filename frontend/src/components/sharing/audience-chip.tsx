"use client";

import { Building2, Lock, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * Who a resource is for, on its card (#2072): everyone, its departments by name,
 * or nobody beyond whoever it was shared with.
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
  const [Icon, label] =
    visibility === "org"
      ? [Building2, t("everyone")]
      : groups.length > 0
        ? [Users, groupsLabel(groups, t)]
        : [Lock, t("chipPrivate")];
  return (
    <span
      className={cn("text-muted-foreground flex min-w-0 items-center gap-1 text-xs", className)}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="truncate">{label}</span>
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
