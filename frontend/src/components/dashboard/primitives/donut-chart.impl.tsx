"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

export interface DonutSegment {
  name: string;
  value: number;
  /** The ring's fill. A CSS colour, usually a `var(--color-*)` token. */
  color: string;
}

/**
 * The donut body. The legend deliberately lives outside (a text list with the
 * numbers printed), because several of the fills sit below 3:1 against the
 * card - deliberately, since a large block takes a tint - so colour is never
 * the only channel carrying which segment is which.
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
        {/* The gap between arcs is the card showing through, not a paddingAngle:
            a rotational gap grows with the arc it precedes, so a 1% sliver
            ended up mostly gap. A 2px stroke in the surface colour separates
            every pair by the same amount however small either is. */}
        <Pie
          data={segments}
          dataKey="value"
          nameKey="name"
          innerRadius="70%"
          outerRadius="94%"
          cornerRadius={3}
          stroke="var(--color-card)"
          strokeWidth={2}
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
