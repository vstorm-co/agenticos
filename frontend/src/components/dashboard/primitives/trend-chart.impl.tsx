"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AREA_FILL_OPACITY, LINE_WIDTH } from "@/lib/dashboard/system";

export interface TrendPoint {
  label: string;
  value: number;
}

/**
 * A single-series area chart for daily counts. Split out so pages don't
 * statically import recharts - loaded on demand via `next/dynamic`. Colours
 * are CSS variables read inline: recharts renders raw SVG, which Tailwind
 * classes cannot reach.
 */
export function TrendChartImpl({ data }: { data: TrendPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      {/* The right margin is the last tick's other half. Recharts anchors an
          edge tick on the point, so with no margin `08-15` was drawn half
          outside the plot and clipped by the card - which is what "the chart
          has ugly margins" was. The left is zero because the y-axis reserves
          its own width. */}
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        {/* Solid, and one step off the surface. A dashed grid adds ink that is
            not data and reads as "projection" or "threshold" when it is only a
            grid. */}
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.06)" vertical={false} />
        <XAxis
          dataKey="label"
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          minTickGap={28}
          tickMargin={8}
          interval="preserveStartEnd"
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "oklch(from var(--color-foreground) l c h / 0.45)",
          }}
        />
        <YAxis
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={32}
          tickCount={4}
          allowDecimals={false}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "oklch(from var(--color-foreground) l c h / 0.45)",
          }}
        />
        <Tooltip
          cursor={{ stroke: "oklch(from var(--color-foreground) l c h / 0.15)" }}
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "12px",
          }}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
        />
        {/* A flat wash rather than a gradient: the fill says "under the line",
            and a ramp invents a second encoding down the y-axis that no data
            asked for. */}
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-chart)"
          strokeWidth={LINE_WIDTH}
          fill="var(--color-chart)"
          fillOpacity={AREA_FILL_OPACITY}
          dot={false}
          // The hovered point, drawn in the surface with the line's own colour
          // around it - the cursor line alone says which column, never which
          // series when a card grows a second one.
          activeDot={{
            r: 3.5,
            fill: "var(--color-card)",
            stroke: "var(--color-chart)",
            strokeWidth: LINE_WIDTH,
          }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
