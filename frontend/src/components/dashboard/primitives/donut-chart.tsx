"use client";

import dynamic from "next/dynamic";
import { useLocale } from "next-intl";

import type { DonutSegment } from "./donut-chart.impl";
import { formatShare } from "../format";
import { cn } from "@/lib/utils";

const DonutChartImpl = dynamic(() => import("./donut-chart.impl").then((m) => m.DonutChartImpl), {
  ssr: false,
  loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-full" />,
});

export interface DonutLegendRow {
  name: string;
  value: number;
  /** The ring colour this row belongs to, so the key always matches the ring. */
  color: string;
  /** This row's fraction of the whole, printed beside the count. */
  share?: number;
}

/**
 * Donut plus its text legend, which is where the detail lives.
 *
 * The two are given separately because they answer different questions, and one
 * array cannot be both: the ring holds only the segments with something in
 * them - an arc of zero is a colour in the key and no ink on the ring - while
 * the legend lists every category the window could have held, including the
 * ones it did not, because "no runs were refused for budget" is an answer.
 *
 * Each legend row carries the colour of the segment it names, so the key can
 * never show a colour the ring does not draw. A row at zero is dimmed rather
 * than dropped, and every row prints its count: colour separates the arcs,
 * it never carries the value.
 */
export function DonutChart({
  segments,
  legend,
  centerLabel,
  centerSub,
  className,
}: {
  segments: DonutSegment[];
  /** Defaults to the ring's own segments, for a chart whose two agree. */
  legend?: DonutLegendRow[];
  centerLabel: string;
  centerSub: string;
  className?: string;
}) {
  const locale = useLocale();
  const rows: DonutLegendRow[] = legend ?? segments;
  return (
    <div className={cn("flex items-center gap-5", className)}>
      <div className="size-32 shrink-0 sm:size-36">
        <DonutChartImpl segments={segments} centerLabel={centerLabel} centerSub={centerSub} />
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {rows.map((row) => (
          <li
            key={row.name}
            className={cn("flex items-center gap-2 text-xs", row.value === 0 && "opacity-45")}
          >
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: row.color }}
              aria-hidden
            />
            <span className="text-muted-foreground min-w-0 flex-1 truncate">{row.name}</span>
            {row.share !== undefined ? (
              <span className="text-muted-foreground/70 shrink-0 tabular-nums">
                {formatShare(row.share, locale)}
              </span>
            ) : null}
            <span className="text-foreground w-8 shrink-0 text-right font-medium tabular-nums">
              {row.value.toLocaleString(locale)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type { DonutSegment };
