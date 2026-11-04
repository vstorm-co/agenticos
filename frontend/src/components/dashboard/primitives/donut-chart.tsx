"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
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
  /** Where this row's own rows live - the same hand-off a bar row carries. */
  href?: string;
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
 * never show a colour the ring does not draw. A row at zero is kept rather
 * than dropped, and every row prints its count: colour separates the arcs,
 * it never carries the value.
 *
 * Side by side when the card is wide enough for the names, and the key under
 * the ring when it is not: beside a ring in a third of the page, "Awaiting
 * approval" and "Budget exceeded" were cut to their first word.
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
    // The container is the outer box and the layout the inner one: a container
    // query reads an ancestor, never the element it is written on.
    <div className={cn("@container flex flex-col justify-center", className)}>
      <div className="flex flex-col items-center gap-4 @[26rem]:flex-row @[26rem]:gap-5">
        <div className="size-32 shrink-0 sm:size-36">
          <DonutChartImpl segments={segments} centerLabel={centerLabel} centerSub={centerSub} />
        </div>
        <ul className="w-full min-w-0 space-y-2 @[26rem]:flex-1">
          {rows.map((row) => (
            <li key={row.name} className="flex items-center gap-2 text-xs">
              <span
                className="size-2.5 shrink-0 rounded-[3px]"
                style={{ background: row.color }}
                aria-hidden
              />
              {/* A row with runs behind it is a link to them; one with none is
                text, because a link to an empty list is a dead end dressed as
                an answer. */}
              {row.href && row.value > 0 ? (
                <Link
                  href={row.href}
                  className="text-muted-foreground hover:text-foreground min-w-0 flex-1 truncate underline-offset-4 hover:underline"
                >
                  {row.name}
                </Link>
              ) : (
                <span className="text-muted-foreground min-w-0 flex-1 truncate">{row.name}</span>
              )}
              {row.share !== undefined ? (
                <span className="text-muted-foreground shrink-0 tabular-nums">
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
    </div>
  );
}

export type { DonutSegment };
