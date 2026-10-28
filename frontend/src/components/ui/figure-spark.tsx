"use client";

import { useLocale } from "next-intl";
import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";

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
 * product. No axes or grid; a tooltip reveals the bucket behind the trend without
 * turning the compact figure into a full chart.
 */
export function FigureSpark({
  spark,
  color,
  labels,
  formatValue,
  name,
}: {
  spark: number[];
  color: string;
  labels?: string[];
  formatValue?: (value: number) => string;
  name?: string;
}) {
  const locale = useLocale();
  const numbers = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  // `useId` answers with characters (`:` or `«`) a `url(#…)` reference cannot hold.
  const washId = `wash-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={spark.map((value, index) => ({ index, value }))}>
        <defs>
          <linearGradient id={washId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={AREA_FILL_OPACITY} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Tooltip
          isAnimationActive={false}
          reverseDirection={{ y: true }}
          allowEscapeViewBox={{ x: true, y: true }}
          labelFormatter={(index) => labels?.[Number(index)] ?? ""}
          formatter={(value) =>
            typeof value === "number"
              ? formatValue
                ? formatValue(value)
                : numbers.format(value)
              : ""
          }
          contentStyle={{
            background: "var(--color-popover)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            color: "var(--color-popover-foreground)",
            fontSize: 12,
          }}
          itemStyle={{ color: "var(--color-popover-foreground)" }}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
        />
        <Area
          name={name}
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#${washId})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
