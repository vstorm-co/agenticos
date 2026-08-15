"use client";

import { useTranslations } from "next-intl";

import { completedShare, formatCompletedShare, statusTally } from "@/lib/run-outcomes";
import { deltaPercent, formatUsd } from "../format";
import { DeltaChip, Metric } from "../metric";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * The four numbers the rest of the page is the detail of: how much ran, how
 * much of it worked, what it cost, and how many people it reached.
 *
 * It exists because of what a healthy organization used to open on. The first
 * band is "Needs attention", and in a deployment where nothing is wrong every
 * card in it is an empty state - so five "nothing here" boxes were the first
 * answer the dashboard gave, and the numbers began below the fold. A summary
 * strip is also the shape Activity opens with, so the two pages now answer
 * their first question the same way.
 *
 * Nothing here is a second request: every figure is a slice of the composed
 * `/stats/usage` response the cards below already share, deduplicated into one
 * query by key. The completed share reads `run-outcomes`, so this strip and the
 * Outcomes donut two rows down can never print different percentages of the
 * same window.
 */
export function SummaryWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.summary");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="summary">
        {(usage) => {
          const runs = usage.total_runs ?? 0;
          const runsDelta = deltaPercent(runs, usage.previous_total_runs ?? 0);
          const spend = Number(usage.cost?.period_usd ?? 0);
          const spendDelta = deltaPercent(spend, Number(usage.cost?.previous_period_usd ?? 0));
          const active = usage.active_users?.active ?? 0;
          return (
            <div className="grid flex-1 grid-cols-2 content-center gap-5 lg:grid-cols-4">
              <Metric
                label={t("runs")}
                value={runs.toLocaleString()}
                delta={
                  runsDelta !== null ? (
                    <DeltaChip delta={runsDelta} label={t("delta")} />
                  ) : undefined
                }
              />
              <Metric
                label={t("completed")}
                value={formatCompletedShare(completedShare(statusTally(usage.by_status ?? [])))}
                caption={t("completedOf", { total: runs })}
              />
              <Metric
                label={t("spend")}
                value={formatUsd(usage.cost?.period_usd)}
                delta={
                  spendDelta !== null ? (
                    <DeltaChip delta={spendDelta} label={t("delta")} rising="bad" />
                  ) : undefined
                }
              />
              <Metric
                label={t("people")}
                value={active.toLocaleString()}
                caption={t("ofMembers", { total: usage.active_users?.total_members ?? 0 })}
              />
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
