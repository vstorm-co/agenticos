"use client";

import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { seriesColor, TRACK_TOKEN } from "@/lib/dashboard/system";
import { StackedMeter } from "../primitives/stacked-meter";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Adoption as a count, deliberately not a table of names: "14 of 23 members
 * ran an agent" answers the steward's question without shipping a
 * surveillance table. Anonymous widget visitors carry no user and are not
 * counted as people.
 */
export function ActiveUsersWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.active-users");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="active-users" options={options}>
        {(usage) => {
          const active = usage.active_users?.active ?? 0;
          const members = usage.active_users?.total_members ?? 0;
          return (
            <div className="flex h-full flex-col gap-5">
              <Figure
                value={active.toLocaleString()}
                unit={t("ofMembers", { total: members })}
                caption={t("subline")}
              />
              {/* The count against the roster it is a count of. "1 of 2" and
                  "1 of 200" are the same figure and not the same news, and a
                  card that only prints the numerator makes the reader do the
                  division. */}
              {members > 0 ? (
                <StackedMeter
                  segments={[
                    { label: t("ran"), value: active, color: seriesColor(1) },
                    {
                      label: t("didNot"),
                      value: Math.max(0, members - active),
                      color: TRACK_TOKEN,
                    },
                  ]}
                />
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
