"use client";

import dynamic from "next/dynamic";

import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import type { RatingsPoint } from "./ratings-trend.impl";

const RatingsTrendImpl = dynamic(
  () => import("./ratings-trend.impl").then((m) => m.RatingsTrendImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

/**
 * The quality block: the headline share of positive answers, then how the
 * thumbs moved day by day - where quality stands and where it is going.
 */
export function RatingsTrend({
  positivePercent,
  subline,
  data,
}: {
  positivePercent: number;
  subline: string;
  data: RatingsPoint[];
}) {
  return (
    <div className="flex h-full flex-col gap-2">
      <div>
        <span className="text-foreground text-2xl font-semibold tabular-nums">
          {positivePercent}%
        </span>
        <p className="text-muted-foreground text-xs">{subline}</p>
      </div>
      <div className={cn(CHART_MIN_HEIGHT, "flex-1")}>
        <RatingsTrendImpl data={data} />
      </div>
    </div>
  );
}

export type { RatingsPoint };
