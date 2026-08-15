"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";

import { AREA_FILL_OPACITY } from "@/lib/dashboard/system";

/**
 * The trend hint under a {@link Figure}'s number.
 *
 * Split out so a page rendering figures without a sparkline never statically
 * imports recharts; the parent loads it through `next/dynamic`.
 *
 * Drawn in the chart token rather than in ink: it is data, and it obeys the
 * same flat wash and stroke the full-size charts do - a sparkline that invented
 * its own opacity is how two drawings of one number stop looking like one
 * product. No axes, no grid, no tooltip: the figure above it *is* the value, so
 * the shape only has to say which way it has been going.
 */
export function FigureSpark({ spark }: { spark: number[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={spark.map((value, index) => ({ index, value }))}>
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-chart)"
          strokeWidth={1.5}
          fill="var(--color-chart)"
          fillOpacity={AREA_FILL_OPACITY}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
