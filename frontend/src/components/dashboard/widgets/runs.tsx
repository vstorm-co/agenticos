"use client";

import { useTranslations } from "next-intl";

import { deltaPercent } from "../format";
import { TrendChart } from "../primitives/trend-chart";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** The adoption curve: runs per day, with the previous window for scale. */
export function RunsWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.runs");

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="runs">
        {(usage) => {
          const total = usage.total_runs ?? 0;
          const delta = deltaPercent(total, usage.previous_total_runs ?? 0);
          return (
            <div className="flex h-full flex-col gap-2">
              <div className="flex items-baseline gap-2">
                <span className="text-foreground text-2xl font-semibold tabular-nums">
                  {total.toLocaleString()}
                </span>
                <span className="text-muted-foreground text-xs">{t("unit")}</span>
                {delta !== null ? (
                  <span
                    className={`text-xs font-medium ${delta >= 0 ? "text-success" : "text-destructive"}`}
                  >
                    {delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}% {t("delta")}
                  </span>
                ) : null}
              </div>
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
