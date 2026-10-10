"use client";

import { Building2, Lock, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import { useGroups } from "@/hooks";
import { cn } from "@/lib/utils";
import { useOrgStore } from "@/stores";
import type { Visibility } from "@/types/sharing";

/** Who a new resource reaches: the whole organization, its creator, or chosen groups. */
export interface Audience {
  mode: "org" | "private" | "groups";
  group_ids: string[];
}

export const EVERYONE: Audience = { mode: "org", group_ids: [] };

/**
 * What a create request sends for an audience.
 *
 * "Groups" with none picked yet sends the whole organization: a choice half made
 * is not a reason to hide the new thing from everyone.
 */
export function audiencePayload(audience: Audience): {
  visibility: Visibility;
  group_ids: string[];
} {
  if (audience.mode === "groups" && audience.group_ids.length > 0) {
    return { visibility: "private", group_ids: audience.group_ids };
  }
  return { visibility: audience.mode === "private" ? "private" : "org", group_ids: [] };
}

/**
 * The one control that decides who a new agent, skill, knowledge base or context
 * file reaches (#2072).
 *
 * The organization by default, because a company's agents and knowledge are the
 * company's; narrowed to the creator, or to departments by picking groups, which
 * the server turns into a private resource shared with each of them.
 */
export function AudiencePicker({
  value,
  onChange,
  disabled,
}: {
  value: Audience;
  onChange: (audience: Audience) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("audience");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups } = useGroups(orgId);

  const options = [
    { mode: "org", icon: Building2, label: t("everyone"), hint: t("everyoneHint") },
    { mode: "private", icon: Lock, label: t("onlyMe"), hint: t("onlyMeHint") },
    {
      mode: "groups",
      icon: Users,
      label: t("groups"),
      hint: groups.length === 0 ? t("noGroupsYet") : t("groupsHint"),
    },
  ] as const;

  const toggleGroup = (groupId: string) =>
    onChange({
      mode: "groups",
      group_ids: value.group_ids.includes(groupId)
        ? value.group_ids.filter((id) => id !== groupId)
        : [...value.group_ids, groupId],
    });

  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label={t("label")} className="grid gap-2 sm:grid-cols-3">
        {options.map((option) => (
          <button
            key={option.mode}
            type="button"
            role="radio"
            aria-checked={value.mode === option.mode}
            disabled={disabled || (option.mode === "groups" && groups.length === 0)}
            onClick={() =>
              onChange({
                mode: option.mode,
                group_ids: option.mode === "groups" ? value.group_ids : [],
              })
            }
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors disabled:opacity-50",
              value.mode === option.mode ? "border-foreground/40 bg-accent" : "hover:bg-accent/50",
            )}
          >
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <option.icon className="h-4 w-4" aria-hidden />
              {option.label}
            </span>
            <span className="text-muted-foreground text-xs">{option.hint}</span>
          </button>
        ))}
      </div>
      {value.mode === "groups" && (
        <div role="group" aria-label={t("chooseGroups")} className="flex flex-wrap gap-1.5">
          {groups.map((group) => {
            const on = value.group_ids.includes(group.id);
            return (
              <button
                key={group.id}
                type="button"
                aria-pressed={on}
                disabled={disabled}
                onClick={() => toggleGroup(group.id)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border py-0.5 pr-3 pl-0.5 text-xs transition-colors",
                  on ? "border-foreground/40 bg-accent font-medium" : "hover:bg-accent/50",
                )}
              >
                <GroupIcon
                  icon={group.icon}
                  className="h-5 w-5 rounded-full [&_svg]:h-3 [&_svg]:w-3"
                />
                {group.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
