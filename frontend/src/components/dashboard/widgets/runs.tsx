"use client";

import { useTranslations } from "next-intl";

import { DeltaChip, Figure } from "@/components/ui";

import { resolveStyle } from "@/lib/dashboard/registry";
import { deltaPercent } from "../format";
import { TrendChart } from "../primitives/trend-chart";
import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/** The adoption curve: runs per day, with the previous window for scale. */
export function RunsWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.runs");
  const style = resolveStyle("runs", options?.style);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="runs" options={options}>
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
                variant={style === "bars" ? "bars" : "area"}
                className={cn(CHART_MIN_HEIGHT, "flex-1")}
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
