"use client";

import { CHART_TOOLTIP_CONTENT, CHART_TOOLTIP_ITEM, CHART_TOOLTIP_LABEL } from "@/lib/chart-styles";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { RatingsByDay } from "@/types/stats";

/**
 * Likes/dislikes per day. A dashboard-local copy of the admin ratings chart's
 * configuration rather than an import from that route's folder - a page must
 * not become a component library by accident. The day-point is the shared
 * `RatingsByDay`, the one shape the summaries and this chart agree on (#559).
 */
export function RatingsTrendImpl({ data }: { data: RatingsByDay[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 0 }} barGap={2}>
        {/* Solid hairline: a dashed grid is ink that is not data. */}
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          dataKey="date"
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={12}
          tickLine={false}
          axisLine={false}
          minTickGap={24}
          tickMargin={8}
          interval="preserveStartEnd"
          // Month and day, as the runs chart beside it prints them: the year is
          // the same on every tick, and four full dates were wider than the
          // card, so the last one was cut at its edge.
          tickFormatter={(date: string) => date.slice(5)}
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
          width={36}
          allowDecimals={false}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "var(--color-muted-foreground)",
          }}
        />
        <Tooltip
          cursor={{ fill: "oklch(from var(--color-foreground) l c h / 0.04)" }}
          contentStyle={CHART_TOOLTIP_CONTENT}
          itemStyle={CHART_TOOLTIP_ITEM}
          labelStyle={CHART_TOOLTIP_LABEL}
        />
        {/* Two categories, so two colours - and the same two the outcomes ring
            spends on "it worked" and "it did not", because a reader who has
            learned that pairing on one card should not have to learn it again
            on this one. They were `foreground` at 75% and 30%: two greys, which
            is a stacked bar chart with the key thrown away. */}
        <Bar dataKey="likes" fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={24} />
        <Bar dataKey="dislikes" fill="var(--series-4)" radius={[4, 4, 0, 0]} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}
