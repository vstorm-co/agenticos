"use client";

import dynamic from "next/dynamic";

import type { DonutSegment } from "./donut-chart.impl";
import { cn } from "@/lib/utils";

const DonutChartImpl = dynamic(() => import("./donut-chart.impl").then((m) => m.DonutChartImpl), {
  ssr: false,
  loading: () => <div className="bg-foreground/5 h-full w-full animate-pulse rounded-full" />,
});

/**
 * Donut plus its text legend. Every segment repeats as dot + name + count,
 * because colour alone is a CVD trap and the counts are the actual answer.
 */
export function DonutChart({
  segments,
  centerLabel,
  centerSub,
  className,
}: {
  segments: DonutSegment[];
  centerLabel: string;
  centerSub: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-4", className)}>
      <div className="size-36 shrink-0">
        <DonutChartImpl segments={segments} centerLabel={centerLabel} centerSub={centerSub} />
      </div>
      <ul className="min-w-0 flex-1 space-y-1.5">
        {segments.map((segment) => (
          <li key={segment.name} className="flex items-center gap-2 text-xs">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: segment.color }}
              aria-hidden
            />
            <span className="text-muted-foreground min-w-0 flex-1 truncate">{segment.name}</span>
            <span className="text-foreground font-medium tabular-nums">
              {segment.value.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type { DonutSegment };
