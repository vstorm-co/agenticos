"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

export interface DonutSegment {
  name: string;
  value: number;
  /** A CSS colour, usually a `var(--color-*)` token. */
  color: string;
}

/**
 * The donut body. The legend deliberately lives outside (a text list with the
 * numbers printed), because two of the five tones sit below 3:1 contrast -
 * colour is never the only channel.
 */
export function DonutChartImpl({
  segments,
  centerLabel,
  centerSub,
}: {
  segments: DonutSegment[];
  centerLabel: string;
  centerSub: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "12px",
          }}
        />
        <Pie
          data={segments}
          dataKey="value"
          nameKey="name"
          innerRadius="68%"
          outerRadius="92%"
          paddingAngle={2}
          strokeWidth={0}
          isAnimationActive={false}
        >
          {segments.map((segment) => (
            <Cell key={segment.name} fill={segment.color} />
          ))}
        </Pie>
        <text
          x="50%"
          y="47%"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="var(--color-foreground)"
          fontSize={22}
          fontWeight={600}
        >
          {centerLabel}
        </text>
        <text
          x="50%"
          y="60%"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="var(--color-muted-foreground)"
          fontSize={11}
        >
          {centerSub}
        </text>
      </PieChart>
    </ResponsiveContainer>
  );
}
