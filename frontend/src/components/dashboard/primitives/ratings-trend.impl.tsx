"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface RatingsPoint {
  date: string;
  likes: number;
  dislikes: number;
}

/**
 * Likes/dislikes per day. A dashboard-local copy of the admin ratings chart's
 * configuration rather than an import from that route's folder - a page must
 * not become a component library by accident.
 */
export function RatingsTrendImpl({ data }: { data: RatingsPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={2}>
        {/* Solid hairline: a dashed grid is ink that is not data. */}
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          dataKey="date"
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
          cursor={{ fill: "oklch(from var(--color-foreground) l c h / 0.04)" }}
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "12px",
          }}
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
