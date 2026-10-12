"use client";

import { Building2, Server, User, UsersRound, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { DashboardView } from "@/lib/dashboard/layouts";
import type { Group } from "@/types/groups";

import { SEGMENTED_CLASS, segment } from "./segmented";

const VIEW_ICONS: Record<DashboardView, LucideIcon> = {
  me: User,
  org: Building2,
  group: UsersRound,
  deployment: Server,
};

/**
 * Whose dashboard this is: the reader's own, the organization's, one group's or
 * the whole deployment's. Only the views the reader may open are offered, and a
 * reader with one view sees no switch at all - a control with one choice is
 * furniture.
 *
 * The group view names its group beside the switch, from the organization's own
 * list, so "Group" is never a page about nobody.
 */
export function ViewSwitcher({
  views,
  view,
  onViewChange,
  groups,
  groupId,
  onGroupChange,
}: {
  views: readonly DashboardView[];
  view: DashboardView;
  onViewChange: (view: DashboardView) => void;
  groups: Group[];
  groupId: string | null;
  onGroupChange: (groupId: string) => void;
}) {
  const t = useTranslations("dashboard.views");
  if (views.length < 2) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <div className={SEGMENTED_CLASS} role="group" aria-label={t("label")}>
        {views.map((option) => {
          const Icon = VIEW_ICONS[option];
          return (
            <button
              key={option}
              type="button"
              aria-pressed={view === option}
              onClick={() => onViewChange(option)}
              className={segment(view === option)}
            >
              <Icon className="size-4" aria-hidden />
              {t(`${option}.label`)}
            </button>
          );
        })}
      </div>
      {view === "group" && groupId !== null ? (
        <Select value={groupId} onValueChange={onGroupChange}>
          <SelectTrigger className="h-9 w-auto min-w-44 rounded-full" aria-label={t("group.pick")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {groups.map((group) => (
              <SelectItem key={group.id} value={group.id} textValue={group.name}>
                <span className="flex items-center gap-2">
                  <GroupIcon icon={group.icon} className="size-5 rounded-md [&_svg]:size-3" />
                  {group.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
