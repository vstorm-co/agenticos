"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// The sparkline is the only part that needs recharts, so it loads on demand -
// a page rendering figures without one never pays for the library.
const FigureSpark = dynamic(() => import("./figure-spark").then((m) => m.FigureSpark), {
  ssr: false,
  loading: () => <div className="h-full w-full" />,
});

export interface FigureProps {
  /** The small line above the number. Omitted when the card's title says it. */
  label?: string;
  /**
   * The number. A node, not a string, because a figure that can be reached is
   * worth more than one that cannot - the p95 links to the runs behind it.
   */
  value: ReactNode;
  /** The unit beside it - "runs", "of 23 members". Never baked into `value`. */
  unit?: string;
  /** A `<DeltaChip>`, when the window has a predecessor to compare against. */
  delta?: ReactNode;
  caption?: ReactNode;
  /** A caption that says the figure could not be read, rather than describing it. */
  captionTone?: "muted" | "destructive";
  /** Recent points, drawn as a trend hint under the number. */
  spark?: number[];
  /** `lg` is for the one figure a view leads with. */
  size?: "md" | "lg";
  className?: string;
}

/**
 * One figure, drawn the one way this product draws a figure.
 *
 * There were three: `StatCard` on Admin (with a delta and a sparkline nothing
 * on the dashboard used), `Metric` on the dashboard, and a private `Figure`
 * inside `ActivityFigures`. The same number changed typeface between a card and
 * the page its "see all" pointed at.
 *
 * The number is **sans, semibold, with the font's own figures** - deliberately
 * not `tabular-nums` and not the mono face both predecessors used. Equal-width
 * digits are for columns that align vertically (a table row, an axis tick); on
 * a large standalone number they make `121` look loose, and a mono face on a
 * headline reads as decoration rather than as data.
 */
export function Figure({
  label,
  value,
  unit,
  delta,
  caption,
  captionTone = "muted",
  spark,
  size = "md",
  className,
}: FigureProps) {
  return (
    <div className={cn("flex min-w-0 flex-col", className)}>
      {label ? (
        <p className="text-muted-foreground text-xs tracking-wide uppercase">{label}</p>
      ) : null}
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span
          className={cn(
            "text-foreground font-semibold tracking-tight",
            size === "lg" ? "text-4xl" : "text-2xl",
          )}
        >
          {value}
        </span>
        {unit ? <span className="text-muted-foreground text-xs">{unit}</span> : null}
        {delta}
      </div>
      {caption ? (
        <p
          className={cn(
            "mt-1 text-xs",
            captionTone === "destructive" ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {caption}
        </p>
      ) : null}
      {spark && spark.length >= 2 ? (
        <div className="mt-3 h-9 w-full">
          <FigureSpark spark={spark} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * The change against the previous window of the same length.
 *
 * `rising` says which direction is the good one, because it is not the same
 * question on every card: more runs is adoption, more spend is a bill. The
 * caller answers it; the chip only paints. Zero is neither, and takes the
 * neutral dash rather than being rounded into whichever tone `>= 0` means.
 */
export function DeltaChip({
  delta,
  label,
  rising = "good",
}: {
  delta: number;
  /** What the comparison is against, already translated ("vs the last 30 days"). */
  label: string;
  rising?: "good" | "bad";
}) {
  const good = delta > 0 ? rising === "good" : rising === "bad";
  const tone = delta === 0 ? "text-muted-foreground" : good ? "text-success" : "text-destructive";
  const Arrow = delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-baseline gap-1 text-xs">
      <span className={cn("inline-flex items-center gap-0.5 font-medium", tone)}>
        <Arrow className="size-3" aria-hidden />
        {Math.abs(delta)}%
      </span>
      <span className="text-muted-foreground/70">{label}</span>
    </span>
  );
}

/**
 * A {@link Figure} that is the whole card - the shape Admin's counters and
 * Activity's three figures take, where nothing else shares the surface.
 */
export function FigureCard({
  icon: Icon,
  className,
  ...figure
}: FigureProps & { icon?: LucideIcon }) {
  return (
    <Card className={className}>
      <CardContent className="p-5">
        {Icon ? (
          <div className="flex items-start justify-between gap-2">
            <Figure {...figure} />
            <Icon className="text-muted-foreground/60 mt-0.5 size-4 shrink-0" aria-hidden />
          </div>
        ) : (
          <Figure {...figure} />
        )}
      </CardContent>
    </Card>
  );
}
