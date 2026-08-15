"use client";

import dynamic from "next/dynamic";

import type { TrendPoint } from "./trend-chart.impl";

const TrendChartImpl = dynamic(() => import("./trend-chart.impl").then((m) => m.TrendChartImpl), {
  ssr: false,
  loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
});

/** The lazy wrapper widgets import; the recharts body loads on demand. */
export function TrendChart({
  data,
  variant = "area",
  className,
}: {
  data: TrendPoint[];
  /**
   * A line under a wash, or a column per bucket. The same series either way:
   * an area reads as a shape over time and columns read as discrete amounts,
   * and which of the two a daily count *is* depends on the reader.
   */
  variant?: "area" | "bars";
  className?: string;
}) {
  return (
    <div className={className ?? "h-40"}>
      <TrendChartImpl data={data} variant={variant} />
    </div>
  );
}

export type { TrendPoint };
