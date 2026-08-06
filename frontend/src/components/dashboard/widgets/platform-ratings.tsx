"use client";

import { useTranslations } from "next-intl";

import { useAdminRatingsSummary } from "@/hooks";
import { RatingsTrend } from "../primitives/ratings-trend";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** Answer quality across every organization, over the page's period. */
export function PlatformRatingsWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.platform-ratings");
  const { summary, isLoading, error, refetch } = useAdminRatingsSummary(period);

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !summary || summary.total_ratings === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <RatingsTrend
          positivePercent={Math.round((summary.like_count / summary.total_ratings) * 100)}
          subline={t("subline", { count: summary.total_ratings })}
          data={summary.ratings_by_day}
        />
      )}
    </WidgetFrame>
  );
}
