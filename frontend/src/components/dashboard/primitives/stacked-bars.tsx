"use client";

import dynamic from "next/dynamic";

import type { StackedPoint, StackedSeries } from "./stacked-bars.impl";

const StackedBarsImpl = dynamic(
  () => import("./stacked-bars.impl").then((m) => m.StackedBarsImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

/** The lazy wrapper, with its key under the chart: colour never names a series alone. */
export function StackedBars({
  data,
  series,
  className,
}: {
  data: StackedPoint[];
  series: StackedSeries[];
  className?: string;
}) {
  return (
    <div className="space-y-2">
      <div className={className ?? "h-48"}>
        <StackedBarsImpl data={data} series={series} />
      </div>
      <ul className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {series.map((one) => (
          <li key={one.key} className="flex items-center gap-1.5">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: one.color }} />
            {one.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export type { StackedPoint, StackedSeries };
