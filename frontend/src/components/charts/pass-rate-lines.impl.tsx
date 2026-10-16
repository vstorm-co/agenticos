"use client";

import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { LINE_WIDTH } from "@/lib/dashboard/system";

export interface PassRatePoint {
  /** The run's place in order, oldest first - the x axis, so runs sit evenly apart. */
  index: number;
  /** 0..1. */
  rate: number;
  /** What ran, as short as the axis has room for: "v7", "D". */
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
  points: PassRatePoint[];
}

const AXIS = "oklch(from var(--color-foreground) l c h / 0.45)";
const QUARTERS = [0, 0.25, 0.5, 0.75, 1];

function PointTip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: PassRatePoint }[];
}) {
  const point = payload?.[0]?.payload;
  if (!active || point === undefined) return null;
  return (
    <div className="bg-card space-y-0.5 rounded-xl border px-3 py-2 text-xs shadow-sm">
      <p className="font-medium">{point.title}</p>
      {point.details.map((line) => (
        <p key={line} className="text-muted-foreground">
          {line}
        </p>
      ))}
    </div>
  );
}

/**
 * Pass rate by run, one line per series, each point in its verdict's colour
 * and opening its run. Split out so pages don't statically import recharts;
 * colours are CSS variables because recharts renders raw SVG, which Tailwind
 * cannot reach.
 */
export function PassRateLinesImpl({
  lines,
  from,
  to,
}: {
  lines: PassRateLine[];
  from: number;
  to: number;
}) {
  const router = useRouter();
  const ticks = new Map(lines.flatMap((line) => line.points.map((p) => [p.index, p.tick])));
  const indexes = [...ticks.keys()].sort((a, b) => a - b);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          type="number"
          dataKey="index"
          domain={[from - 0.5, to + 0.5]}
          ticks={indexes}
          tickFormatter={(index: number) => ticks.get(index) ?? ""}
          interval="preserveStartEnd"
          minTickGap={8}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{ fill: AXIS }}
        />
        <YAxis
          dataKey="rate"
          domain={[0, 1]}
          ticks={QUARTERS}
          tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={36}
          tick={{ fill: AXIS }}
        />
        <Tooltip
          content={<PointTip />}
          cursor={{ stroke: "oklch(from var(--color-foreground) l c h / 0.15)" }}
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
                r={5}
                stroke={props.payload?.color ?? line.color}
                strokeWidth={2}
                fill={props.payload?.draft ? "var(--color-card)" : props.payload?.color}
                className="cursor-pointer"
                onClick={() => props.payload && router.push(props.payload.href)}
              />
            )}
            activeDot={(props: { cx?: number; cy?: number; payload?: PassRatePoint }) => (
              <circle
                cx={props.cx}
                cy={props.cy}
                r={7}
                stroke={props.payload?.color ?? line.color}
                strokeWidth={2}
                fill={props.payload?.draft ? "var(--color-card)" : props.payload?.color}
                className="cursor-pointer"
                onClick={() => props.payload && router.push(props.payload.href)}
              />
            )}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
