"use client";

import { useTranslations } from "next-intl";

import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Adoption as a count, deliberately not a table of names: "14 of 23 members
 * ran an agent" answers the steward's question without shipping a
 * surveillance table. Anonymous widget visitors carry no user and are not
 * counted as people.
 */
export function ActiveUsersWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.active-users");

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="active-users">
        {(usage) => (
          <div className="flex h-full flex-col justify-center gap-1">
            <p className="text-foreground text-2xl font-semibold tabular-nums">
              {t("headline", {
                active: usage.active_users?.active ?? 0,
                total: usage.active_users?.total_members ?? 0,
              })}
            </p>
            <p className="text-muted-foreground text-xs">{t("subline")}</p>
          </div>
        )}
      </UsageBody>
    </WidgetFrame>
  );
}
