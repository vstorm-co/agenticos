"use client";

import { useRouter } from "next/navigation";
import {
  Brush,
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
  /** What ran and when, as short as the axis has room for: "v7 · 07:55", "Draft · Oct 21". */
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
interface Row {
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

function PointTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const point = payload?.[0]?.payload.point;
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
 * and opening its run. Given `recent`, over a range a person drags to widen or
 * narrow - the newest `recent` runs to begin with; without it, every run. Split
 * out so pages don't statically import recharts; colours are CSS variables
 * because recharts renders raw SVG, which Tailwind cannot reach.
 */
export function PassRateLinesImpl({
  lines,
  recent,
  rangeLabel,
}: {
  lines: PassRateLine[];
  recent: number | null;
  rangeLabel: string;
}) {
  const router = useRouter();
  const data = rows(lines);
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
        strokeWidth={2}
        fill={point.draft ? "var(--color-card)" : point.color}
        className="cursor-pointer"
        onClick={() => router.push(point.href)}
      />
    );
  };
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="oklch(from var(--color-foreground) l c h / 0.07)" vertical={false} />
        <XAxis
          dataKey="tick"
          padding={{ left: 12, right: 12 }}
          interval="preserveStartEnd"
          minTickGap={8}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{ fill: AXIS }}
        />
        <YAxis
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
            dataKey={line.key}
            name={line.name}
            stroke={line.color}
            strokeWidth={LINE_WIDTH}
            strokeDasharray={line.dash}
            connectNulls
            isAnimationActive={false}
            dot={(props: { cx?: number; cy?: number; payload?: Row }) => dot(props, line, 5)}
            activeDot={(props: { cx?: number; cy?: number; payload?: Row }) => dot(props, line, 7)}
          />
        ))}
        {recent !== null && (
          <Brush
            dataKey="tick"
            height={28}
            travellerWidth={10}
            // Recharts draws these labels outside the handles, where the chart's
            // edge cuts them off; the axis above already names the runs in range.
            tickFormatter={() => ""}
            startIndex={Math.max(0, data.length - recent)}
            endIndex={data.length - 1}
            stroke="oklch(from var(--color-foreground) l c h / 0.3)"
            fill="var(--color-card)"
            ariaLabel={rangeLabel}
          >
            {/* Every run in miniature, so the range reads against the whole. */}
            <LineChart data={data}>
              {lines.map((line) => (
                <Line
                  key={line.key}
                  dataKey={line.key}
                  stroke={line.color}
                  strokeWidth={1}
                  strokeDasharray={line.dash}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </Brush>
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
