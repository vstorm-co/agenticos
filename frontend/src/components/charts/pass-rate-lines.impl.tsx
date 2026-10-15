"use client";

import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { LINE_WIDTH } from "@/lib/dashboard/system";
import { formatDateTime } from "@/lib/utils";

export interface PassRatePoint {
  /** When the run was started, in epoch milliseconds - the x axis. */
  at: number;
  /** 0..1. */
  rate: number;
  /** What ran: "v7", "Draft". */
  label: string;
  /** A draft is drawn hollow: it is not a version anyone is talking to. */
  draft: boolean;
  /** One line of tooltip, already in the reader's words. */
  detail: string;
}

export interface PassRateLine {
  key: string;
  name: string;
  color: string;
  points: PassRatePoint[];
}

const AXIS = "oklch(from var(--color-foreground) l c h / 0.45)";

/**
 * Pass rate over time, one line per series, each point labelled with what ran.
 * Split out so pages don't statically import recharts; colours are CSS
 * variables because recharts renders raw SVG, which Tailwind cannot reach.
 */
export function PassRateLinesImpl({ lines, locale }: { lines: PassRateLine[]; locale: string }) {
  const formatTime = (at: number) => formatDateTime(new Date(at).toISOString(), locale);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          type="number"
          dataKey="at"
          domain={["dataMin", "dataMax"]}
          scale="time"
          tickFormatter={formatTime}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          minTickGap={32}
          tick={{ fill: AXIS }}
        />
        <YAxis
          dataKey="rate"
          domain={[0, 1]}
          tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={36}
          tick={{ fill: AXIS }}
        />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "12px",
          }}
          labelFormatter={(at) => formatTime(Number(at))}
          formatter={(_value, _name, item) => [(item.payload as PassRatePoint).detail, ""]}
        />
        {lines.map((line) => (
          <Line
            key={line.key}
            data={line.points}
            dataKey="rate"
            name={line.name}
            stroke={line.color}
            strokeWidth={LINE_WIDTH}
            isAnimationActive={false}
            dot={(props: { cx?: number; cy?: number; index?: number; payload?: PassRatePoint }) => (
              <circle
                key={`${line.key}-${props.index}`}
                cx={props.cx}
                cy={props.cy}
                r={4}
                stroke={line.color}
                strokeWidth={2}
                fill={props.payload?.draft ? "var(--color-card)" : line.color}
              />
            )}
          >
            <LabelList dataKey="label" position="top" fontSize={10} fill={AXIS} />
          </Line>
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
