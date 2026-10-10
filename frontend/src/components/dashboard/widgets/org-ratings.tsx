"use client";

import { useTranslations } from "next-intl";

import { surfaceLabel } from "@/components/runs/surface-icon";
import { useRatingsSummary } from "@/hooks";
import { RatingsTrend } from "../primitives/ratings-trend";
import { WidgetFrame } from "../widget-frame";
import { ThumbsUp } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { SurfaceRatings } from "@/types/stats";
import type { DashboardWidgetProps } from "./types";

/** The only card on the page that answers "is any of it good" for the org. */
export function OrgRatingsWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.org-ratings");
  const { ratings, isLoading, error, refetch } = useRatingsSummary({
    from: period.from,
    to: period.to,
  });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !ratings || ratings.total_ratings === 0 ? (
        <WidgetEmptyBody
          icon={ThumbsUp}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <>
          <RatingsTrend
            positivePercent={Math.round((ratings.like_count / ratings.total_ratings) * 100)}
            subline={t("subline", { count: ratings.total_ratings })}
            data={ratings.ratings_by_day}
          />
          <SurfaceSplit surfaces={ratings.ratings_by_surface ?? []} />
        </>
      )}
    </WidgetFrame>
  );
}

/**
 * How answers are rated on each surface, once there is more than one (#2084):
 * an agent rated well in the console and badly in Slack is answering two
 * audiences, and one percentage hides which.
 */
function SurfaceSplit({ surfaces }: { surfaces: SurfaceRatings[] }) {
  const t = useTranslations("dashboard.widgets.org-ratings");
  const tSurfaces = useTranslations("pages.runs");
  if (surfaces.length < 2) return null;
  return (
    <ul className="text-muted-foreground mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {surfaces.map((entry) => (
        <li key={entry.surface}>
          {t("bySurface", {
            surface: surfaceLabel(entry.surface, tSurfaces),
            percent: Math.round((entry.likes / (entry.likes + entry.dislikes)) * 100),
          })}
        </li>
      ))}
    </ul>
  );
}
