"use client";

import dynamic from "next/dynamic";

import type { TrendPoint } from "./trend-chart.impl";

const TrendChartImpl = dynamic(() => import("./trend-chart.impl").then((m) => m.TrendChartImpl), {
  ssr: false,
  loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
});

/** The lazy wrapper widgets import; the recharts body loads on demand. */
export function TrendChart({ data, className }: { data: TrendPoint[]; className?: string }) {
  return (
    <div className={className ?? "h-40"}>
      <TrendChartImpl data={data} />
    </div>
  );
}

export type { TrendPoint };
