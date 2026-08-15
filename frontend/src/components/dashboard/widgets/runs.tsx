"use client";

import { useTranslations } from "next-intl";

import { DeltaChip, Figure } from "@/components/ui";

import { deltaPercent } from "../format";
import { TrendChart } from "../primitives/trend-chart";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** The adoption curve: runs per day, with the previous window for scale. */
export function RunsWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.runs");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="runs">
        {(usage) => {
          const total = usage.total_runs ?? 0;
          const delta = deltaPercent(total, usage.previous_total_runs ?? 0);
          return (
            <div className="flex h-full flex-col gap-3">
              <Figure
                value={total.toLocaleString()}
                unit={t("unit")}
                delta={delta !== null ? <DeltaChip delta={delta} label={t("delta")} /> : undefined}
              />
              <TrendChart
                className="min-h-32 flex-1"
                data={(usage.by_day ?? []).map((day) => ({
                  label: day.date.slice(5),
                  value: day.runs,
                }))}
              />
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
