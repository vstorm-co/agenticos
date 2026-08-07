"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useMembers } from "@/hooks";
import { useOrgStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

const ROLE_ORDER = ["owner", "admin", "builder", "operator", "member", "viewer"] as const;

/**
 * The team and its role split. Gated on members:manage as a layout call, not
 * a boundary - the members endpoint itself is open to any member, and the
 * card is here because the person who manages the roster acts on it.
 */
export function MembersWidget({ title }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.members");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members, total, isLoading, error, refetch } = useMembers(activeOrgId ?? "");

  const split = new Map<string, number>();
  for (const member of members) {
    split.set(member.role, (split.get(member.role) ?? 0) + 1);
  }

  return (
    <WidgetFrame title={title} seeAll={activeOrgId ? ROUTES.ORG_MEMBERS(activeOrgId) : undefined}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : total <= 1 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-3">
          <p className="text-foreground text-2xl font-semibold tabular-nums">{total}</p>
          <BarList
            items={ROLE_ORDER.filter((role) => split.has(role)).map((role) => ({
              label: t(`roles.${role}`),
              value: split.get(role) ?? 0,
            }))}
          />
          {activeOrgId ? (
            <Link
              href={ROUTES.ORG_MEMBERS(activeOrgId)}
              className="text-muted-foreground hover:text-foreground text-xs"
            >
              {t("view")}
            </Link>
          ) : null}
        </div>
      )}
    </WidgetFrame>
  );
}
