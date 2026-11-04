"use client";

import { useTranslations } from "next-intl";

import { ActivityChart, ActivityFigures } from "@/components/admin/background-jobs/job-activity";
import { useBackgroundJobsActivity } from "@/hooks/use-background-jobs";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The deployment's job queue over the last day (#2248): how much finished, how
 * much of it died, and when. Always the day, whatever the page's period: the
 * queue keeps fourteen days and charts by the hour, so a month would be empty
 * where it is not wrong. The Background jobs page has the week and every kind.
 */
export function BackgroundJobsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.background-jobs");
  const { data, isPending, error, refetch } = useBackgroundJobsActivity("day");
  const quiet = data?.buckets.every(
    (bucket) => bucket.succeeded + bucket.dead + bucket.cancelled === 0,
  );
  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isPending ? (
        <WidgetSkeleton variant="chart" />
      ) : error || !data ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : quiet ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="grid flex-1 content-center gap-5 lg:grid-cols-[11rem_1fr]">
          <ActivityFigures activity={data} compact />
          <ActivityChart activity={data} className="h-40" />
        </div>
      )}
    </WidgetFrame>
  );
}
