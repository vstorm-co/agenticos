"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface StackedSeries {
  key: string;
  label: string;
  /** A CSS colour: recharts draws SVG, which a Tailwind class cannot reach. */
  color: string;
}

export type StackedPoint = { label: string } & Record<string, number | string>;

/**
 * Columns of counts split by outcome, on the axes `TrendChart` draws. Split out
 * so pages do not import recharts statically - loaded via `next/dynamic`.
 */
export function StackedBarsImpl({
  data,
  series,
}: {
  data: StackedPoint[];
  series: StackedSeries[];
}) {
  const last = series.length - 1;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
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
          width={36}
          tickCount={4}
          allowDecimals={false}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "oklch(from var(--color-foreground) l c h / 0.45)",
          }}
        />
        <Tooltip
          cursor={{ fill: "oklch(from var(--color-foreground) l c h / 0.05)" }}
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "12px",
          }}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
        />
        {series.map((one, index) => (
          <Bar
            key={one.key}
            dataKey={one.key}
            name={one.label}
            stackId="stack"
            fill={one.color}
            maxBarSize={28}
            // Only the top of the stack is rounded, or every seam shows a notch.
            radius={index === last ? [3, 3, 0, 0] : 0}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
