"use client";

import { Clock } from "lucide-react";
import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { useUsageStats } from "@/hooks";
import { TrendChart } from "../primitives/trend-chart";
import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The caller's own runs - scope=own, open to every role. The pending line
 * answers "why is my agent stuck" for someone who cannot see the approval
 * queue; deciding stays behind approvals:decide, so there is no button here.
 */
export function MyActivityWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-activity");
  const { usage, isLoading, error, refetch } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own" },
  );

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !usage || !usage.total_runs ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col gap-3">
          <Figure
            value={usage.total_runs.toLocaleString()}
            unit={t("unit")}
            delta={
              usage.pending_approvals ? (
                <span className="text-warning flex items-center gap-1 text-xs">
                  <Clock className="size-3" aria-hidden />
                  {t("pending", { count: usage.pending_approvals })}
                </span>
              ) : undefined
            }
          />
          <TrendChart
            className={cn(CHART_MIN_HEIGHT, "flex-1")}
            data={(usage.by_day ?? []).map((day) => ({
              label: day.date.slice(5),
              value: day.runs,
            }))}
          />
        </div>
      )}
    </WidgetFrame>
  );
}
