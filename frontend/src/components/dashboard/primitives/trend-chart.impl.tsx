"use client";

import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

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
  const gradientId = useId();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-chart)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--color-chart)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="oklch(from var(--color-foreground) l c h / 0.07)"
          vertical={false}
        />
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
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-chart)"
          strokeWidth={1.5}
          fill={`url(#${gradientId})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
