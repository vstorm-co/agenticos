"use client";

import { useTranslations } from "next-intl";

import { AnimatedAmount, AnimatedTally, DeltaChip, Figure } from "@/components/ui";

import { completedShare, formatCompletedShare, statusTally } from "@/lib/run-outcomes";
import { timelineOf } from "@/lib/dashboard/timeline";
import { deltaPercent, formatUsd } from "../format";
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
export function SummaryWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.summary");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="summary" loadingVariant="metrics" options={options}>
        {(usage) => {
          const runs = usage.total_runs ?? 0;
          const runsDelta = deltaPercent(runs, usage.previous_total_runs ?? 0);
          const spend = Number(usage.cost?.period_usd ?? 0);
          const spendDelta = deltaPercent(spend, Number(usage.cost?.previous_period_usd ?? 0));
          const active = usage.active_users?.active ?? 0;
          // Three of the four figures have a series behind them, from the same
          // response - `timeline` carries runs, completed and cost per step, at
          // a step the server chose for how much there is.
          // The fourth does not: distinct people cannot be summed across days
          // without counting somebody twice, so it is drawn as the share of the
          // members it reached instead.
          const days = timelineOf(usage);
          return (
            // Stretching, not centred: three of the four figures carry a daily
            // series, and a series that fills the card is the shape this strip
            // is for. Centred, the numbers sat in the middle of the card with
            // their sparklines pinned under them and the height its owner gave
            // the card spent on nothing.
            <div className="grid flex-1 grid-cols-2 gap-5 @[40rem]/widget:grid-cols-4">
              <Figure
                tone="indigo"
                label={t("runs")}
                value={<AnimatedTally value={runs} />}
                delta={
                  runsDelta !== null ? (
                    <DeltaChip delta={runsDelta} label={t("delta")} />
                  ) : undefined
                }
                spark={days.map((day) => day.runs)}
              />
              <Figure
                tone="teal"
                label={t("completed")}
                value={formatCompletedShare(completedShare(statusTally(usage.by_status ?? [])))}
                caption={t("completedOf", { total: runs })}
                spark={days.map((day) => day.completed)}
              />
              <Figure
                tone="violet"
                label={t("spend")}
                value={
                  <AnimatedAmount
                    value={usage.cost?.period_usd}
                    label={t("spendLabel", { amount: formatUsd(usage.cost?.period_usd) })}
                  />
                }
                delta={
                  spendDelta !== null ? (
                    <DeltaChip delta={spendDelta} label={t("delta")} rising="bad" />
                  ) : undefined
                }
                spark={days.map((day) => Number(day.cost_usd))}
              />
              <Figure
                tone="amber"
                label={t("people")}
                value={<AnimatedTally value={active} />}
                caption={t("ofMembers", { total: usage.active_users?.total_members ?? 0 })}
                meter={
                  usage.active_users?.total_members
                    ? active / usage.active_users.total_members
                    : undefined
                }
              />
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
