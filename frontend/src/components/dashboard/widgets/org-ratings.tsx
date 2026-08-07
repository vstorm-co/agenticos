"use client";

import { useTranslations } from "next-intl";

import { useRatingsSummary } from "@/hooks";
import { RatingsTrend } from "../primitives/ratings-trend";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The only card on the page that answers "is any of it good" for the org. */
export function OrgRatingsWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.org-ratings");
  const { ratings, isLoading, error, refetch } = useRatingsSummary({
    from: period.from,
    to: period.to,
  });

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !ratings || ratings.total_ratings === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <RatingsTrend
          positivePercent={Math.round((ratings.like_count / ratings.total_ratings) * 100)}
          subline={t("subline", { count: ratings.total_ratings })}
          data={ratings.ratings_by_day}
        />
      )}
    </WidgetFrame>
  );
}
