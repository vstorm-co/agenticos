"use client";

import { useTranslations } from "next-intl";

import { completedShare, formatCompletedShare, statusTally } from "@/lib/run-outcomes";
import { DonutChart } from "../primitives/donut-chart";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Five segments covering all six run statuses, so they always sum to the
 * window's total: completed, failed, budget_exceeded, awaiting_approval, and
 * running+cancelled folded into one neutral "other". The awaiting count is
 * the same number the approvals card lists - the two can never disagree,
 * because both read the same rows.
 */
export function OutcomesWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.outcomes");

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="outcomes">
        {(usage) => {
          const byStatus = usage.by_status ?? [];
          const counts = new Map(byStatus.map((row) => [row.status, row.runs]));
          const of = (status: string) => counts.get(status as never) ?? 0;
          // The same tally, and the same shared formula, the Activity version
          // strip reads - so the two never disagree on what "completed" means
          // over one set of rows (docs/design/activity-plan.md §8a.4).
          const tally = statusTally(byStatus);
          const total = tally.total;
          const failed = of("failed");
          const budget = of("budget_exceeded");
          const awaiting = of("awaiting_approval");
          const other = of("running") + of("cancelled");
          const attention = failed + budget;
          const segments = [
            { name: t("status.completed"), value: tally.completed, color: "var(--color-success)" },
            { name: t("status.failed"), value: failed, color: "var(--color-destructive)" },
            { name: t("status.budget_exceeded"), value: budget, color: "var(--color-warning)" },
            { name: t("status.awaiting_approval"), value: awaiting, color: "var(--color-chart)" },
            { name: t("status.other"), value: other, color: "var(--color-muted-foreground)" },
          ];
          return (
            <div className="flex h-full flex-col justify-between gap-2">
              <DonutChart
                segments={segments}
                centerLabel={formatCompletedShare(completedShare(tally))}
                centerSub={t("completed")}
              />
              {attention > 0 ? (
                <p className="text-muted-foreground text-center text-xs">
                  {t("attention", { n: Math.max(1, Math.round(total / attention)) })}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
