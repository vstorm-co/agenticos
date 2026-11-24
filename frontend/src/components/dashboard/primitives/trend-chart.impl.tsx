"use client";

import { CHART_TOOLTIP_CONTENT, CHART_TOOLTIP_ITEM, CHART_TOOLTIP_LABEL } from "@/lib/chart-styles";

import { useTranslations } from "next-intl";
import { useId } from "react";
import { useLocale } from "next-intl";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatUsd } from "../format";

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
export function TrendChartImpl({
  data,
  variant = "area",
  money = false,
}: {
  data: TrendPoint[];
  variant?: "area" | "bars";
  money?: boolean;
}) {
  const locale = useLocale();
  // One axis configuration, two marks. Recharts wants a different chart element
  // for each, and duplicating the axes to switch between them is how the two
  // drift into disagreeing about their own scale.
  const t = useTranslations("pages.runs");
  const Chart = variant === "bars" ? BarChart : AreaChart;
  // `useId` answers with characters (`:` or `«`) a `url(#…)` reference cannot hold.
  const washId = `wash-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <ResponsiveContainer width="100%" height="100%">
      {/* The right margin is the last tick's other half. Recharts anchors an
          edge tick on the point, so with no margin `08-15` was drawn half
          outside the plot and clipped by the card - which is what "the chart
          has ugly margins" was. The left is zero because the y-axis reserves
          its own width. */}
      <Chart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        {/* Solid, and one step off the surface. A dashed grid adds ink that is
            not data and reads as "projection" or "threshold" when it is only a
            grid. */}
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.06)" vertical={false} />
        <XAxis
          dataKey="label"
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={12}
          tickLine={false}
          axisLine={false}
          minTickGap={28}
          tickMargin={8}
          interval="preserveStartEnd"
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "var(--color-muted-foreground)",
          }}
        />
        <YAxis
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={12}
          tickLine={false}
          axisLine={false}
          width={money ? 56 : 40}
          tickCount={4}
          // Counts are whole; dollars are not, and a run costs cents.
          allowDecimals={money}
          tickFormatter={money ? (value: number) => formatUsd(value, locale) : undefined}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "var(--color-muted-foreground)",
          }}
        />
        <Tooltip
          cursor={
            variant === "bars"
              ? { fill: "var(--color-foreground)", fillOpacity: 0.045 }
              : { stroke: "var(--color-muted-foreground)", strokeOpacity: 0.3 }
          }
          contentStyle={CHART_TOOLTIP_CONTENT}
          itemStyle={CHART_TOOLTIP_ITEM}
          labelStyle={CHART_TOOLTIP_LABEL}
          formatter={money ? (value) => formatUsd(Number(value), locale, 4) : undefined}
        />
        <defs>
          <linearGradient id={washId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-chart)" stopOpacity={AREA_FILL_OPACITY} />
            <stop offset="100%" stopColor="var(--color-chart)" stopOpacity={0} />
          </linearGradient>
        </defs>
        {variant === "bars" ? (
          <Bar
            dataKey="value"
            name={t(money ? "cost" : "runs")}
            fill="var(--color-chart-fill)"
            radius={[3, 3, 0, 0]}
            maxBarSize={28}
          />
        ) : (
          <Area
            type="monotone"
            dataKey="value"
            name={t(money ? "cost" : "runs")}
            stroke="var(--color-chart)"
            strokeWidth={LINE_WIDTH}
            fill={`url(#${washId})`}
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
        )}
      </Chart>
    </ResponsiveContainer>
  );
}
