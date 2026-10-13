"use client";

import { Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import {
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useGroups } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { Group } from "@/types/groups";

/** Stands for "every group" in the select, which a group id never is. */
const EVERY = "every";

/**
 * Group a resource list by department (#2124).
 *
 * A group is already who a skill, a context file, a knowledge base or an app
 * reaches (#2072), so a page is grouped by narrowing it to what one group was
 * given - not by a second hierarchy that would have to agree with the first.
 * Absent while the organization has no groups, unless a filter is on, so it
 * can be taken off again.
 */
export function GroupFilter({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (groupId: string | null) => void;
}) {
  const t = useTranslations("groups.filter");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups } = useGroups(orgId);
  if (groups.length === 0 && value === null) return null;
  return (
    <Select value={value ?? EVERY} onValueChange={(next) => onChange(next === EVERY ? null : next)}>
      <SelectTrigger className="w-full sm:w-48" aria-label={t("label")} data-tour="group-filter">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={EVERY}>{t("every")}</SelectItem>
        {groups.map((group) => (
          <SelectItem key={group.id} value={group.id}>
            <span className="flex min-w-0 items-center gap-2">
              <GroupIcon icon={group.icon} className="text-muted-foreground size-4 shrink-0" />
              <span className="truncate">{group.name}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * A list narrowed to one group, with nothing in it.
 *
 * Not the page's own "nothing yet": the organization may hold plenty, and none
 * of it was given to this group - which is said, with where to give it some.
 */
export function NothingSharedWithGroup({ groupId }: { groupId: string }) {
  const t = useTranslations("groups.filter");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups } = useGroups(orgId);
  const group: Group | undefined = groups.find((entry) => entry.id === groupId);
  return (
    <ListCardEmpty
      icon={Users}
      title={t("nothingShared", { name: group?.name ?? "" })}
      description={t("nothingSharedHint")}
    />
  );
}
