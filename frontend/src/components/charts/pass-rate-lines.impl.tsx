"use client";

import { useId } from "react";
import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_TOOLTIP_CONTENT, CHART_TOOLTIP_ITEM, CHART_TOOLTIP_LABEL } from "@/lib/chart-styles";

import { AREA_FILL_OPACITY, LINE_WIDTH } from "@/lib/dashboard/system";

export interface PassRatePoint {
  /** The run's place in order, oldest first - the x axis, so runs sit evenly apart. */
  index: number;
  /** 0..1. */
  rate: number;
  /** When it ran: times within a single day, dates across days. */
  tick: string;
  /** A draft is drawn hollow: it is not a version anyone is talking to. */
  draft: boolean;
  /** The point's own colour - the verdict's, or the line's when there is none. */
  color: string;
  /** The run's page. */
  href: string;
  /** The tooltip's first line, then the rest - already in the reader's words. */
  title: string;
  details: string[];
}

export interface PassRateLine {
  key: string;
  name: string;
  color: string;
  /** The line's dash, which tells it from the others; none draws it solid. */
  dash?: string;
  points: PassRatePoint[];
}

/** One run across every line: its rate under its own line's key, and the point that drew it. */
export interface Row {
  index: number;
  tick: string;
  point: PassRatePoint;
  [line: string]: number | string | PassRatePoint;
}

const AXIS = "oklch(from var(--color-foreground) l c h / 0.45)";
const QUARTERS = [0, 0.25, 0.5, 0.75, 1];

function rows(lines: PassRateLine[]): Row[] {
  return lines
    .flatMap((line) =>
      line.points.map((point) => ({
        index: point.index,
        tick: point.tick,
        point,
        [line.key]: point.rate,
      })),
    )
    .sort((a, b) => a.index - b.index);
}

/**
 * The runs the axis names: the first of each label, so a day of runs reads as
 * one date rather than the same date under every point.
 */
export function axisTicks(data: Row[]): { ticks: number[]; label: Map<number, string> } {
  const ticks: number[] = [];
  const label = new Map<number, string>();
  let previous: string | null = null;
  for (const row of data) {
    if (row.tick === previous) continue;
    previous = row.tick;
    ticks.push(row.index);
    label.set(row.index, row.tick);
  }
  return { ticks, label };
}

function PointTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const point = payload?.[0]?.payload.point;
  if (!active || point === undefined) return null;
  return (
    <div
      style={CHART_TOOLTIP_CONTENT}
      className="max-w-[min(20rem,calc(100vw-2rem))] space-y-1 break-words"
    >
      <p style={CHART_TOOLTIP_ITEM}>{point.title}</p>
      {point.details.map((line) => (
        <p key={line} style={CHART_TOOLTIP_LABEL}>
          {line}
        </p>
      ))}
    </div>
  );
}

/**
 * Pass rate by run, one line per series, each point in its verdict's colour
 * and opening its run, under the dates the runs started. Split out so pages
 * don't statically import recharts; colours are CSS variables because recharts
 * renders raw SVG, which Tailwind cannot reach.
 */
export function PassRateLinesImpl({ lines }: { lines: PassRateLine[] }) {
  const router = useRouter();
  const washId = `eval-wash-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const filled = lines.length === 1 ? lines[0] : undefined;
  const data = rows(lines);
  const axis = axisTicks(data);
  const dot = (
    props: { cx?: number; cy?: number; payload?: Row },
    line: PassRateLine,
    radius: number,
  ) => {
    const point = props.payload?.point;
    if (point === undefined || props.payload?.[line.key] === undefined) {
      return <g key={`${line.key}-${props.payload?.index}`} />;
    }
    return (
      <circle
        key={`${line.key}-${point.index}`}
        cx={props.cx}
        cy={props.cy}
        r={radius}
        stroke={point.color}
        strokeWidth={LINE_WIDTH}
        fill={point.draft ? "var(--color-card)" : point.color}
        className="cursor-pointer"
        onClick={() => router.push(point.href)}
      />
    );
  };
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.06)" vertical={false} />
        <XAxis
          dataKey="index"
          type="number"
          domain={["dataMin", "dataMax"]}
          ticks={axis.ticks}
          tickFormatter={(index: number) => axis.label.get(index) ?? ""}
          padding={{ left: 12, right: 12 }}
          interval="preserveStartEnd"
          minTickGap={28}
          tickMargin={8}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{ fontFamily: "var(--font-mono)", fill: AXIS }}
        />
        <YAxis
          domain={[0, 1]}
          ticks={QUARTERS}
          tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={36}
          tick={{ fontFamily: "var(--font-mono)", fill: AXIS }}
        />
        <Tooltip
          content={<PointTip />}
          cursor={{ stroke: "var(--color-muted-foreground)", strokeOpacity: 0.3 }}
        />
        {filled && (
          <defs>
            <linearGradient id={washId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={filled.color} stopOpacity={AREA_FILL_OPACITY} />
              <stop offset="100%" stopColor={filled.color} stopOpacity={0} />
            </linearGradient>
          </defs>
        )}
        {lines.map((line) => (
          <Area
            type="monotone"
            fill={filled ? `url(#${washId})` : "none"}
            key={line.key}
            dataKey={line.key}
            name={line.name}
            stroke={line.color}
            strokeWidth={LINE_WIDTH}
            strokeDasharray={line.dash}
            connectNulls
            isAnimationActive={false}
            dot={(props: { cx?: number; cy?: number; payload?: Row }) => dot(props, line, 3.5)}
            activeDot={(props: { cx?: number; cy?: number; payload?: Row }) => dot(props, line, 5)}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
