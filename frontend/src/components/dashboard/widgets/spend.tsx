"use client";

import { useTranslations } from "next-intl";

import { useSpend } from "@/hooks";
import { deltaPercent, formatUsd } from "../format";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Two truths about money, deliberately both. The headline and providers are
 * the period's, from the composed stats response, and move with the filter.
 * The fine-print line is the calendar month-to-date from GET /spend - it
 * reconciles against an invoice and must not move with a dashboard filter.
 * The delta's tone is inverted: rising spend is the red direction.
 */
export function SpendWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.spend");
  const { spend } = useSpend();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="spend">
        {(usage) => {
          const cost = usage.cost;
          const current = Number(cost?.period_usd ?? 0);
          const previous = Number(cost?.previous_period_usd ?? 0);
          const delta = deltaPercent(current, previous);
          return (
            <div className="flex h-full flex-col justify-between gap-3">
              <div className="flex items-baseline gap-2">
                <span className="text-foreground text-2xl font-semibold tabular-nums">
                  {formatUsd(cost?.period_usd)}
                </span>
                <span className="text-muted-foreground text-xs">{t("unit")}</span>
                {delta !== null ? (
                  <span
                    className={`text-xs font-medium ${delta > 0 ? "text-destructive" : "text-success"}`}
                  >
                    {delta > 0 ? "▲" : "▼"} {Math.abs(delta)}% {t("delta")}
                  </span>
                ) : null}
              </div>
              <BarList
                items={(cost?.by_provider ?? []).map((row) => ({
                  label: row.provider ?? t("notRecorded"),
                  value: Number(row.cost_usd),
                  display: formatUsd(row.cost_usd),
                }))}
              />
              {spend ? (
                <p className="text-muted-foreground border-border border-t border-dashed pt-2 text-xs">
                  {t("monthToDate", { amount: formatUsd(spend.month_to_date_usd) })}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
