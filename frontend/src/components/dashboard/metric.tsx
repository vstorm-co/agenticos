"use client";

import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * One figure, drawn the one way this product draws a figure.
 *
 * Mono numerals under a small upper-case label, which is what `ActivityFigures`
 * settled on and what a reader crossing from that page to this one is entitled
 * to recognise. Thirteen widgets each printed their headline as
 * `text-2xl font-semibold tabular-nums` with a label above it in whatever size
 * suited that card, so the same number changed typeface between the dashboard
 * and the page it links to.
 *
 * `value` is a node, not a string: the p95 figure is a link to the runs behind
 * it, and a number that can be reached is worth more than one that cannot.
 */
export function Metric({
  label,
  value,
  unit,
  delta,
  caption,
  className,
}: {
  /** The small upper-case line above the number. Omitted on a lone headline. */
  label?: string;
  value: ReactNode;
  /** The unit beside the number - "runs", "of 23 members". Never in the value. */
  unit?: string;
  /** A `<DeltaChip>`, when the window has a predecessor to compare against. */
  delta?: ReactNode;
  caption?: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      {label ? (
        <p className="text-muted-foreground text-[11px] tracking-wide uppercase">{label}</p>
      ) : null}
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-foreground font-mono text-2xl tabular-nums">{value}</span>
        {unit ? <span className="text-muted-foreground text-xs">{unit}</span> : null}
        {delta}
      </div>
      {caption ? <p className="text-muted-foreground mt-1 text-xs">{caption}</p> : null}
    </div>
  );
}

/**
 * The change against the previous window of the same length.
 *
 * `rising` says which direction is the good one, because it is not the same
 * question on every card: more runs is adoption, more spend is a bill. The
 * caller answers it; the chip only paints. Zero is neither - it takes the
 * neutral dash rather than being rounded into whichever tone `>= 0` happens to
 * mean.
 */
export function DeltaChip({
  delta,
  label,
  rising = "good",
}: {
  delta: number;
  /** What the comparison is against, already translated ("vs prior 30 days"). */
  label: string;
  rising?: "good" | "bad";
}) {
  const tone =
    delta === 0
      ? "text-muted-foreground"
      : delta > 0 === (rising === "good")
        ? "text-success"
        : "text-destructive";
  const Arrow = delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-baseline gap-1 text-xs">
      <span className={cn("inline-flex items-center gap-0.5 font-medium tabular-nums", tone)}>
        <Arrow className="size-3" aria-hidden />
        {Math.abs(delta)}%
      </span>
      <span className="text-muted-foreground/70">{label}</span>
    </span>
  );
}
