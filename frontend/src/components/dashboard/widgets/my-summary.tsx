"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { AnimatedAmount, AnimatedTally, Figure } from "@/components/ui";
import { useUsageStats } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { bucketLabeller, timelineOf } from "@/lib/dashboard/timeline";
import { completedShare, formatCompletedShare, statusTally } from "@/lib/run-outcomes";
import { formatUsd } from "../format";
import { WidgetFrame } from "../widget-frame";
import { WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * A person's own period at a glance: their runs, how many finished, what is
 * waiting on a decision and what it cost - four measures, each in its own
 * colour, so they are told apart before they are read.
 *
 * The organization's summary answers the same four questions for everybody;
 * this is the one a member opens their dashboard on. Read from the caller's own
 * usage (`scope=own`), which carries the waiting count the organization's does
 * not. An empty period still draws the four figures at zero: a person with no
 * runs yet is told so by numbers, not by a card that says nothing.
 */
export function MySummaryWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-summary");
  const { usage, isLoading, error, refetch } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own" },
  );

  const locale = useLocale();
  const labels = timelineOf(usage).map(bucketLabeller(usage, locale));

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton variant="metrics" />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : (
        <div className="grid flex-1 grid-cols-2 gap-5 @[40rem]/widget:grid-cols-4">
          <Figure
            tone="indigo"
            label={t("runs")}
            value={<AnimatedTally value={usage?.total_runs ?? 0} />}
            spark={timelineOf(usage).map((step) => step.runs)}
            sparkLabels={labels}
          />
          <Figure
            tone="teal"
            label={t("finished")}
            value={formatCompletedShare(completedShare(statusTally(usage?.by_status ?? [])))}
            caption={t("finishedOf", { total: usage?.total_runs ?? 0 })}
            spark={timelineOf(usage).map((step) => step.completed)}
            sparkLabels={labels}
          />
          <Figure
            tone="amber"
            label={t("waiting")}
            value={<AnimatedTally value={usage?.pending_approvals ?? 0} />}
            caption={
              usage?.pending_approvals ? (
                <Link
                  href={`${ROUTES.RUNS}?tab=approvals`}
                  className="hover:text-foreground underline underline-offset-2"
                >
                  {t("review")}
                </Link>
              ) : (
                t("nothingWaiting")
              )
            }
          />
          <Figure
            tone="violet"
            label={t("spent")}
            value={
              <AnimatedAmount
                value={usage?.cost?.period_usd}
                label={t("spentLabel", { amount: formatUsd(usage?.cost?.period_usd) })}
              />
            }
            spark={timelineOf(usage).map((step) => Number(step.cost_usd))}
            sparkLabels={labels}
            sparkFormat={formatUsd}
          />
        </div>
      )}
    </WidgetFrame>
  );
}
