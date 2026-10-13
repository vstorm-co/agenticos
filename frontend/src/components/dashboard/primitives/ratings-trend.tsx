"use client";

import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import type { RatingsByDay } from "@/types/stats";

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
  data: RatingsByDay[];
}) {
  const t = useTranslations("dashboard");
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <span className="text-foreground text-2xl font-semibold tabular-nums">
            {positivePercent}%
          </span>
          <p className="text-muted-foreground text-xs">{subline}</p>
        </div>
        {/* Two series and no key was a chart that could not be read at all -
            and the swatches are the marks themselves, so the legend cannot
            name a colour the bars do not draw. */}
        <ul className="text-muted-foreground flex shrink-0 items-center gap-3 text-xs">
          {(
            [
              ["likes", "var(--series-2)"],
              ["dislikes", "var(--series-4)"],
            ] as const
          ).map(([key, color]) => (
            <li key={key} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-[3px]"
                style={{ background: color }}
                aria-hidden
              />
              {t(`ratings.${key}`)}
            </li>
          ))}
        </ul>
      </div>
      <div className={cn(CHART_MIN_HEIGHT, "flex-1")}>
        <RatingsTrendImpl data={data} />
      </div>
    </div>
  );
}
