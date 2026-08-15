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
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        {/* Solid, and one step off the surface. A dashed grid adds ink that is
            not data and reads as "projection" or "threshold" when it is only a
            grid. */}
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          dataKey="label"
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          minTickGap={24}
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
          width={28}
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
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
