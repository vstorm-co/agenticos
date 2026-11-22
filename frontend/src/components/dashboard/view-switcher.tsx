"use client";

import { useTabIndicator } from "@/components/ui/use-tab-indicator";
import { Building2, Server, User, UsersRound, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRef, type ReactNode } from "react";

import { GroupIcon } from "@/components/groups/group-icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { SCROLL_FADE, useScrollFade } from "@/components/ui/scroll-fade";
import type { DashboardView } from "@/lib/dashboard/layouts";
import type { Group } from "@/types/groups";

import { cn } from "@/lib/utils";

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
  actions,
}: {
  actions?: ReactNode;
  views: readonly DashboardView[];
  view: DashboardView;
  onViewChange: (view: DashboardView) => void;
  groups: Group[];
  groupId: string | null;
  onGroupChange: (groupId: string) => void;
}) {
  const t = useTranslations("dashboard.views");
  const strip = useRef<HTMLDivElement>(null);
  useScrollFade(strip);
  useTabIndicator(strip, views.length > 1);
  if (views.length < 2)
    return actions ? <div className="mb-4 flex justify-end">{actions}</div> : null;

  return (
    // Tabs, not a second pill control: which dashboard this is sits a level
    // above the period it is read over, and two identical pill rows stacked
    // under one another read as two filters of equal weight.
    <div className="border-border mb-4 grid gap-x-4 gap-y-2 md:grid-cols-[minmax(0,1fr)_auto] md:border-b">
      <div className="border-border min-w-0 border-b md:border-0">
        <div
          ref={strip}
          data-tab-indicator="line"
          className={cn(
            "-mb-px flex h-12 max-w-full scrollbar-none items-stretch gap-5 overflow-x-auto",
            SCROLL_FADE,
          )}
          role="group"
          aria-label={t("label")}
        >
          {views.map((option) => {
            const Icon = VIEW_ICONS[option];
            const active = view === option;
            return (
              <button
                key={option}
                type="button"
                aria-pressed={active}
                onClick={() => onViewChange(option)}
                className={cn(
                  "touch:min-h-11 flex shrink-0 touch-manipulation items-center gap-1.5 border-b-2 px-0.5 text-sm font-medium whitespace-nowrap transition-colors",
                  active
                    ? "border-foreground text-foreground"
                    : "text-muted-foreground hover:text-foreground border-transparent",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {t(`${option}.label`)}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex min-h-12 min-w-0 flex-wrap items-center justify-end gap-2 pb-2 md:pb-0">
        {view === "group" && groupId !== null ? (
          <Select value={groupId} onValueChange={onGroupChange}>
            <SelectTrigger className="h-8 w-auto min-w-44" aria-label={t("group.pick")}>
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
        {actions}
      </div>
    </div>
  );
}
