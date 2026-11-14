"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { LINE_WIDTH } from "@/lib/dashboard/system";

export interface UsageLine {
  key: string;
  name: string;
  color: string;
  /** Past the five series colours a line is told apart by its dash. */
  dash?: string;
}

/** One day: its axis label, then each line's count under the line's key. */
export interface UsageDay {
  day: string;
  [line: string]: number | string;
}

const AXIS = "oklch(from var(--color-foreground) l c h / 0.45)";

/**
 * Counts per day, one line per series. Split out so pages don't statically import
 * recharts; colours are CSS variables because recharts renders raw SVG.
 */
export function UsageLinesImpl({ lines, days }: { lines: UsageLine[]; days: UsageDay[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={days} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          dataKey="day"
          interval="preserveStartEnd"
          minTickGap={24}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{ fill: AXIS }}
        />
        <YAxis
          allowDecimals={false}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={28}
          tick={{ fill: AXIS }}
        />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: 12,
            fontSize: 12,
          }}
        />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
        {lines.map((line) => (
          <Line
            key={line.key}
            dataKey={line.key}
            name={line.name}
            stroke={line.color}
            strokeWidth={LINE_WIDTH}
            strokeDasharray={line.dash}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
