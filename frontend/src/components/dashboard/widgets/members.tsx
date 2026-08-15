"use client";

import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { useMembers } from "@/hooks";
import { useOrgStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import { resolveStyle } from "@/lib/dashboard/registry";
import { seriesColor } from "@/lib/dashboard/system";
import { BarList } from "../primitives/bar-list";
import { StackedMeter } from "../primitives/stacked-meter";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

const ROLE_ORDER = ["owner", "admin", "builder", "operator", "member", "viewer"] as const;

/**
 * The team and its role split. Gated on members:manage as a layout call, not
 * a boundary - the members endpoint itself is open to any member, and the
 * card is here because the person who manages the roster acts on it.
 *
 * The split is one stacked bar rather than a bar list, and the two are not
 * interchangeable: six roles measured against the largest of them answered
 * "who has the most owners", a question nobody has. A stack answers the one
 * the total above it asks - what these people are - and it answers it in a
 * card's width whatever the roster's size.
 *
 * It also fixes the shape the card had: a figure pinned to the top of a cell
 * a taller neighbour had stretched, six bars pinned to the bottom, and a hand's
 * height of nothing between them.
 */
export function MembersWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.members");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members, total, isLoading, error, refetch } = useMembers(activeOrgId ?? "");
  const style = resolveStyle("members", options?.style);

  const split = new Map<string, number>();
  for (const member of members) {
    split.set(member.role, (split.get(member.role) ?? 0) + 1);
  }

  return (
    <WidgetFrame
      title={title}
      hint={hint}
      seeAll={activeOrgId ? ROUTES.ORG_MEMBERS(activeOrgId) : undefined}
    >
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : total <= 1 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col gap-4">
          <Figure value={total.toLocaleString()} unit={t("unit", { count: total })} />
          {style === "bars" ? (
            <BarList
              items={ROLE_ORDER.filter((role) => split.has(role)).map((role) => ({
                label: t(`roles.${role}`),
                value: split.get(role) ?? 0,
              }))}
            />
          ) : (
            <StackedMeter
              segments={ROLE_ORDER.filter((role) => split.has(role)).map((role, index) => ({
                label: t(`roles.${role}`),
                value: split.get(role) ?? 0,
                color: seriesColor(index),
              }))}
            />
          )}
        </div>
      )}
    </WidgetFrame>
  );
}
