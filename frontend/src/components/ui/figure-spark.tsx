"use client";

import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";

import { AREA_FILL_OPACITY } from "@/lib/dashboard/system";

/**
 * The trend hint under a {@link Figure}'s number.
 *
 * Split out so a page rendering figures without a sparkline never statically
 * imports recharts; the parent loads it through `next/dynamic`.
 *
 * Drawn in the chart token rather than in ink: it is data, and it obeys the
 * same wash and stroke the full-size charts do - a sparkline that invented
 * its own opacity is how two drawings of one number stop looking like one
 * product. No axes, no grid, no tooltip: the figure above it *is* the value, so
 * the shape only has to say which way it has been going.
 */
export function FigureSpark({ spark }: { spark: number[] }) {
  // `useId` answers with characters (`:` or `«`) a `url(#…)` reference cannot hold.
  const washId = `wash-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={spark.map((value, index) => ({ index, value }))}>
        <defs>
          <linearGradient id={washId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-chart)" stopOpacity={AREA_FILL_OPACITY} />
            <stop offset="100%" stopColor="var(--color-chart)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-chart)"
          strokeWidth={1.5}
          fill={`url(#${washId})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
