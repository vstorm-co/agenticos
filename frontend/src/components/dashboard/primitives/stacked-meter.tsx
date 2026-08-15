"use client";

import { useLocale } from "next-intl";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { formatShare } from "../format";
import { cn } from "@/lib/utils";

export interface MeterSegment {
  label: string;
  value: number;
  /** The segment's fill - a `var(--series-n)` from the categorical ramp. */
  color: string;
}

/**
 * One bar split into the parts that make it up, and a key under it.
 *
 * The shape a "how is this total made up" card wants when the parts are few and
 * named: a role split, a runtime split, a plan split. A bar list answers "which
 * is biggest"; this answers "what is the whole made of", which is a different
 * question and the one a total at the top of the card has just asked.
 *
 * Segments are the only place the categorical ramp is spent (`system.ts`), and
 * they are parts of one whole, so colour is doing work here rather than
 * re-encoding length. Every part still prints its count and its share: at three
 * pixels wide a segment is a colour with no length to read.
 *
 * A non-zero part is never thinner than 2% of the bar. A single member in an
 * organization of two hundred is a hairline otherwise, and a hairline in a
 * stack of five reads as a border between two others.
 */
export function StackedMeter({
  segments,
  className,
}: {
  segments: MeterSegment[];
  className?: string;
}) {
  const locale = useLocale();
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const parts = segments.filter((segment) => segment.value > 0);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="bg-muted flex h-2.5 gap-[3px] overflow-hidden rounded-full">
        {parts.map((segment) => (
          <Tooltip key={segment.label}>
            <TooltipTrigger asChild>
              <span
                className="h-full first:rounded-l-full last:rounded-r-full"
                style={{
                  background: segment.color,
                  width: `${Math.max(2, (segment.value / total) * 100)}%`,
                }}
              />
            </TooltipTrigger>
            <TooltipContent side="top" className="flex items-center gap-2">
              <span>{segment.label}</span>
              <span className="font-medium">{segment.value.toLocaleString(locale)}</span>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
      <ul className="space-y-1.5">
        {segments.map((segment) => (
          <li
            key={segment.label}
            className={cn("flex items-center gap-2 text-xs", segment.value === 0 && "opacity-45")}
          >
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: segment.color }}
              aria-hidden
            />
            <span className="text-muted-foreground min-w-0 flex-1 truncate">{segment.label}</span>
            <span className="text-muted-foreground/70 shrink-0 tabular-nums">
              {formatShare(total > 0 ? segment.value / total : 0, locale)}
            </span>
            <span className="text-foreground w-8 shrink-0 text-right font-medium tabular-nums">
              {segment.value.toLocaleString(locale)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
